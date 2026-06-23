# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Community QA — verification dimensions + composite quality score.

This is the heart of the eval-driven QA system: it turns ONE end-to-end run (a
harvested snapshot of an owner driving their community) into a multi-dimension
quality assessment — the "generation" record whose composite score is tracked
across git generations (see :mod:`tests.e2e.qa_history`).

Each dimension scores 0-10 with a weight; the composite is a 0-100 quality score.

Dimensions
----------
- ``onboarding``           (structural) — owner greeted the manager and got oriented.
- ``friend_creation``      (structural) — a REAL friend was actually created (a new
                            persona DM appeared) and chatted with. This is the journey
                            the product exists for; it is also the first bug this QA
                            system surfaced (creator narrates instead of firing the
                            create tool under claude_cli) → a perfect gen-over-gen target.
- ``conversation_quality`` (judge)      — the 5-axis friend-conversation judge
                            (:mod:`tests.e2e.community_judge`).
- ``no_hallucination``     (judge)      — friends did not fabricate facts or claim
                            actions/events that never happened.
- ``no_leaks``             (structural) — zero meta / error / tool-call leaks.
- ``responsiveness``       (structural) — every driven DM got a distinct reply, no stall.

Backend honesty (the iron rule, inherited from community_judge): the LLM-judge
dimensions only run on a real backend with the CLI present; on echo they are SKIPPED
(excluded from the composite) rather than scored with fabricated numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from tests.e2e import community_verdict, community_judge
from tests.e2e.quality_judge import MODEL as _JUDGE_MODEL, call_haiku, extract_json

# Stable kernel ids for the two built-in agents every fresh community ships with.
# A "friend" is any DM that is NOT one of these two — i.e. a persona the owner made.
MGR_CHANNEL = "dm-agent-mgr-001"
CREATOR_CHANNEL = "dm-agent-creator-001"

# Default gate: a generation "passes" at >= 70/100 overall. Tunable per call.
DEFAULT_MIN_OVERALL = 70


# ── dimension spec + result ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class Dimension:
    key: str
    label: str          # human label (Korean, shown in report/dashboard)
    weight: float       # relative weight in the composite
    kind: str           # "structural" | "judge"
    what: str           # one-line "what this measures" (surfaced in the report)


# The registry. Order = display order. Weights reflect product priority: the lived
# experience (conversation quality) and the core journey (friend creation) matter most.
DIMENSIONS: list[Dimension] = [
    Dimension("onboarding", "온보딩", 1.0, "structural",
              "막 들어온 오너가 매니저(유나)한테 인사하고 오리엔테이션을 받는가"),
    Dimension("friend_creation", "친구 생성", 1.5, "structural",
              "오너 요청으로 진짜 새 친구가 생성되어 그 친구와 대화까지 이어지는가"),
    Dimension("conversation_quality", "대화 품질", 2.0, "judge",
              "친구들의 답이 사람 친구처럼 자연스럽고 일관·맥락있게 좋은가 (5축)"),
    Dimension("no_hallucination", "환각 없음", 1.5, "judge",
              "친구가 사실을 지어내거나 하지 않은 일을 했다고 하지 않는가"),
    Dimension("no_leaks", "누수 없음", 1.0, "structural",
              "메타(자신=AI 고백)·에러·도구블록 누수가 0 인가"),
    Dimension("responsiveness", "응답성", 1.0, "structural",
              "구동된 모든 DM 이 (서로 다른) 답을 받고 멈춤·오류가 없는가"),
]
_BY_KEY = {d.key: d for d in DIMENSIONS}


@dataclass
class DimResult:
    key: str
    label: str
    kind: str
    weight: float
    what: str
    score: Optional[float]      # 0-10, or None if skipped
    passed: Optional[bool]      # None if skipped
    detail: str
    skipped: bool = False
    skip_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "kind": self.kind,
            "weight": self.weight, "what": self.what, "score": self.score,
            "passed": self.passed, "detail": self.detail,
            "skipped": self.skipped, "skip_reason": self.skip_reason,
        }


# ── transcript helper (owner ↔ friends, for the judges) ──────────────────────────

def _transcript(snap: dict, *, limit_chars: int = 6000) -> str:
    """Flatten the snapshot's channels into a readable owner↔friend transcript."""
    owner_id = _owner_id(snap)
    labels = snap.get("labels") or {}
    lines: list[str] = []
    for ch, msgs in (snap.get("channels") or {}).items():
        if not msgs:
            continue
        lines.append(f"# {labels.get(ch, ch)}")
        for m in msgs:
            who = "오너" if (m.get("is_user") or m.get("speaker") == owner_id) \
                else (m.get("speaker") or "?")
            txt = (m.get("message") or m.get("text") or "").strip().replace("\n", " ")
            if txt:
                lines.append(f"{who}: {txt}")
    return "\n".join(lines)[:limit_chars]


def _owner_id(snap: dict) -> str:
    oid = snap.get("owner_id")
    if oid:
        return oid
    for msgs in (snap.get("channels") or {}).values():
        for m in msgs or []:
            if m.get("is_user") and m.get("speaker"):
                return m["speaker"]
    return ""


def _friend_channels(snap: dict) -> list[str]:
    """DM channels that are an actual created friend (not the built-in mgr/creator)."""
    return sorted(
        ch for ch in (snap.get("channels") or {})
        if ch.startswith("dm-") and ch not in (MGR_CHANNEL, CREATOR_CHANNEL)
    )


def _replies_in(snap: dict, ch: str, owner_id: str) -> list[str]:
    return [
        (m.get("message") or m.get("text") or "").strip()
        for m in (snap.get("channels") or {}).get(ch, [])
        if m.get("speaker") and m.get("speaker") != owner_id and not m.get("is_user")
        and (m.get("message") or m.get("text") or "").strip()
    ]


# ── structural dimension evaluators ──────────────────────────────────────────────

def _eval_onboarding(snap: dict, owner_id: str) -> DimResult:
    d = _BY_KEY["onboarding"]
    mgr_msgs = (snap.get("channels") or {}).get(MGR_CHANNEL, [])
    owner_greeted = any(m.get("is_user") or m.get("speaker") == owner_id for m in mgr_msgs)
    mgr_replies = _replies_in(snap, MGR_CHANNEL, owner_id)
    if owner_greeted and mgr_replies:
        score, passed = 10.0, True
        detail = f"오너가 유나한테 인사 → 유나 응답 {len(mgr_replies)}건 (온보딩 정상)"
    elif owner_greeted:
        score, passed = 3.0, False
        detail = "오너가 유나한테 인사했으나 유나 응답 없음 (온보딩 stall)"
    else:
        score, passed = 0.0, False
        detail = "매니저(유나) DM 온보딩 흔적 없음"
    return DimResult(d.key, d.label, d.kind, d.weight, d.what, score, passed, detail)


def _eval_friend_creation(snap: dict, owner_id: str) -> DimResult:
    d = _BY_KEY["friend_creation"]
    friend_chs = _friend_channels(snap)
    if not friend_chs:
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, 0.0, False,
                         "새 친구가 생성되지 않음 (유나·하나 DM 뿐 — create_agent_profile 미발동)")
    chatted = [ch for ch in friend_chs if _replies_in(snap, ch, owner_id)]
    if chatted:
        score, passed = 10.0, True
        detail = f"진짜 친구 {len(friend_chs)}명 생성 + 대화 ({', '.join(chatted)})"
    else:
        score, passed = 6.0, False
        detail = f"친구 {len(friend_chs)}명 생성됐으나 아직 대화 없음 ({', '.join(friend_chs)})"
    return DimResult(d.key, d.label, d.kind, d.weight, d.what, score, passed, detail)


def _eval_no_leaks(metrics: dict) -> DimResult:
    d = _BY_KEY["no_leaks"]
    meta = int(metrics.get("meta_leaks", 0) or 0)
    err = int(metrics.get("error_leaks", 0) or 0)
    omw = int(metrics.get("owner_meta_leaks", 0) or 0)
    total = meta + err + omw
    score = max(0.0, 10.0 - 3.0 * total)
    passed = total == 0
    detail = (f"메타 {meta} · 에러 {err} · 오너메타 {omw} = 총 {total} 누수"
              + (" (clean)" if total == 0 else ""))
    return DimResult(d.key, d.label, d.kind, d.weight, d.what, score, passed, detail)


def _eval_responsiveness(snap: dict, metrics: dict, owner_id: str) -> DimResult:
    d = _BY_KEY["responsiveness"]
    driven = [ch for ch in (snap.get("channels") or {}) if ch.startswith("dm-")]
    with_reply = [ch for ch in driven if _replies_in(snap, ch, owner_id)]
    runner_error = metrics.get("runner_error")
    distinct_ok = metrics.get("replies_distinct_checked", True)
    if not driven:
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, 0.0, False,
                         "구동된 DM 이 없음")
    ratio = len(with_reply) / len(driven)
    score = round(10.0 * ratio, 1)
    if runner_error:
        score = min(score, 4.0)
    if not distinct_ok:
        score = min(score, 6.0)
    passed = ratio == 1.0 and not runner_error and distinct_ok
    detail = (f"{len(with_reply)}/{len(driven)} DM 응답"
              + (f" · runner_error={runner_error}" if runner_error else "")
              + ("" if distinct_ok else " · 반복응답 의심"))
    return DimResult(d.key, d.label, d.kind, d.weight, d.what, score, passed, detail)


# ── judge dimension evaluators ───────────────────────────────────────────────────

_HALLUCINATION_PROMPT = """너는 'AI 친구 커뮤니티' 제품의 채팅을 검수하는 사실성 채점자야.
친구(AI)들이 **사실을 지어내거나, 하지 않은 일을 했다고 하거나, 앞말과 모순되는 말**을
했는지 본다. (말투·성격은 평가 대상 아님 — 오직 사실성/일관성.)

환각의 예: 실제로 안 만났는데 "어제 너랑 카페 갔잖아", 존재하지 않는 공통 추억 날조,
오너가 말한 적 없는 정보를 기정사실화, 같은 대화 안에서 자기 설정(나이·이름·관계) 번복.

0~10 으로 채점. 10 = 환각/허위/모순 전혀 없음, 0 = 심각하게 지어냄.
엄격하게 JSON 만:
{{"score": 0-10, "pass": true|false, "rationale": "한 줄 (어떤 환각이 있었는지/없었는지)"}}
pass = score >= 7.

--- 대화 기록 ---
{transcript}
"""


def _eval_conversation_quality(snap: dict, do_judge: bool, min_score: int) -> DimResult:
    d = _BY_KEY["conversation_quality"]
    if not do_judge:
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, None, None,
                         "echo / CLI 미존재 — judge 생략", skipped=True, skip_reason="no-judge")
    q = community_judge.judge_conversation(
        transcript=_transcript(snap), goal=snap.get("goal", ""),
        context=snap.get("context", ""), min_score=min_score)
    if q.get("status") != "scored" or q.get("overall") is None:
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, None, None,
                         f"judge 실패: {q.get('rationale','')[:80]}",
                         skipped=True, skip_reason="judge-error")
    axes = " · ".join(f"{k} {v}" for k, v in (q.get("scores") or {}).items())
    return DimResult(d.key, d.label, d.kind, d.weight, d.what,
                     float(q["overall"]), bool(q.get("pass")),
                     f"5축 [{axes}] — {q.get('rationale','')[:120]}")


def _eval_no_hallucination(snap: dict, do_judge: bool) -> DimResult:
    d = _BY_KEY["no_hallucination"]
    if not do_judge:
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, None, None,
                         "echo / CLI 미존재 — judge 생략", skipped=True, skip_reason="no-judge")
    transcript = _transcript(snap)
    if not transcript.strip():
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, None, None,
                         "대화 없음 — judge 생략", skipped=True, skip_reason="empty")
    raw = call_haiku(_HALLUCINATION_PROMPT.format(transcript=transcript), timeout=120)
    if not raw or raw.startswith("__ERROR__"):
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, None, None,
                         f"judge 실패: {(raw or '')[:80]}", skipped=True, skip_reason="judge-error")
    data = extract_json(raw) or {}
    try:
        score = max(0.0, min(10.0, float(data.get("score"))))
    except (TypeError, ValueError):
        return DimResult(d.key, d.label, d.kind, d.weight, d.what, None, None,
                         "judge 응답 파싱 실패", skipped=True, skip_reason="parse-error")
    passed = bool(data.get("pass")) if "pass" in data else score >= 7
    return DimResult(d.key, d.label, d.kind, d.weight, d.what, score, passed,
                     (data.get("rationale") or "").strip()[:120])


# ── composite + public API ───────────────────────────────────────────────────────

def _composite(results: list[DimResult]) -> Optional[float]:
    active = [r for r in results if not r.skipped and r.score is not None]
    wtot = sum(r.weight for r in active)
    if not wtot:
        return None
    wsum = sum(r.score * r.weight for r in active)
    return round(100.0 * wsum / (10.0 * wtot), 1)


def assess(snap: dict, *, run_judges: Optional[bool] = None,
           min_overall: int = DEFAULT_MIN_OVERALL,
           conversation_min: int = community_judge.DEFAULT_MIN_SCORE) -> dict:
    """Full multi-dimension QA assessment of one run snapshot → a generation record.

    ``run_judges`` forces / skips the LLM-judge dimensions (default: auto — real
    backend AND the claude CLI present, mirroring community_judge). Returns a dict:
    ``{overall_score, passed, min_overall, dimensions:[...], failing:[keys],
    backend, judged, generated_at(None — caller stamps)}``.
    """
    owner_id = _owner_id(snap)
    verdict = community_verdict.judge_snapshot(snap)
    metrics = verdict.get("metrics", {}) or {}

    backend = (snap.get("backend") or "echo").lower()
    if run_judges is None:
        run_judges = backend not in ("echo", "") and community_judge.judge_available()

    results: list[DimResult] = [
        _eval_onboarding(snap, owner_id),
        _eval_friend_creation(snap, owner_id),
        _eval_conversation_quality(snap, run_judges, conversation_min),
        _eval_no_hallucination(snap, run_judges),
        _eval_no_leaks(metrics),
        _eval_responsiveness(snap, metrics, owner_id),
    ]

    overall = _composite(results)
    passed = overall is not None and overall >= min_overall
    failing = [r.key for r in results if r.passed is False]

    return {
        "overall_score": overall,
        "passed": passed,
        "min_overall": min_overall,
        "backend": backend,
        "judged": bool(run_judges),
        "structural_status": verdict.get("status"),
        "structural_verdict": verdict.get("verdict"),
        "dimensions": [r.as_dict() for r in results],
        "failing": failing,
        "judge_model": _JUDGE_MODEL,
    }
