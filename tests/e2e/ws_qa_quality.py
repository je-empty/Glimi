# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi WORKSPACE EDD dimensions — the domain layer on top of :mod:`glimi.edd`.

The generic EDD scaffolding (the :class:`~glimi.edd.Dimension` / :class:`DimResult`
model, composite 0-100 scoring, git-anchored generation history) lives in **core**
(``glimi.edd``) so Community and Workspace share it. This module is the Workspace
analogue of :mod:`tests.e2e.qa_quality`: it supplies only what is *Workspace-
specific* — the six dimensions and how to evaluate them from a harvested owner↔team
run snapshot.

Dimensions
----------
- ``task_decomposition``       (structural) — the manager (coordinator) split the
                                goal across the live specialist roster (delegated
                                into every dynamic ``dm-*``).
- ``deliverable_completeness`` (structural) — the core deliverable actually exists:
                                non-empty, no ``[오류]``, substantial, structured.
                                CRITICAL — a broken core deliverable = whole-run FAIL.
- ``deliverable_quality``      (judge)      — the 5-axis deliverable judge
                                (:func:`tests.e2e.ws_judge.judge_deliverable`).
- ``coordination_quality``     (structural) — real bidirectional A2A happened in the
                                ``internal-*`` channels (both sides actually spoke).
- ``instruction_following``    (judge)      — each round's deliverable actually
                                addressed that round's owner instruction.
- ``no_leaks``                 (structural) — zero meta / error leaks.

Judge dimensions only run on a real backend with the CLI present; on echo they are
SKIPPED (excluded from the composite), never scored with fabricated numbers — the
same backend-honesty rule Community and ``ws_judge``/``ws_report`` follow.
"""
from __future__ import annotations

from typing import Optional

from glimi.edd import Dimension, DimResult, build_assessment
from tests.e2e import ws_verdict, ws_judge
from tests.e2e.quality_judge import MODEL as _JUDGE_MODEL, call_haiku, extract_json

# Default gate: a generation "passes" at >= 70/100 overall. Tunable per call.
DEFAULT_MIN_OVERALL = 70

# A substantial, structured document (not a one-line ack) — mirrors ws_verdict's bar.
_DELIVERABLE_LEN_THRESHOLD = 400


# The Workspace dimension registry (order = display order). Weights reflect product
# priority: the deliverable IS the product, so completeness (the critical gate) and
# quality carry the most weight; coordination + decomposition are the team mechanics
# that produce it.
DIMENSIONS: list[Dimension] = [
    Dimension("task_decomposition", "과제 분해", 1.5, "structural",
              "매니저가 목표를 살아있는 전문가 로스터(동적 dm-*)에 모두 위임했는가"),
    Dimension("deliverable_completeness", "산출물 완결성", 2.0, "structural",
              "핵심 산출물이 비어있지/오류이지 않고 충분히 길고 구조를 갖췄는가",
              critical=True),  # 이게 깨지면 제품의 존재 이유가 깨진 것 → 전체 FAIL
    Dimension("deliverable_quality", "산출물 품질", 2.0, "judge",
              "산출물이 완결성·구조·실행가능성·구체성·정확성 기준으로 얼마나 좋은가 (5축)"),
    Dimension("coordination_quality", "협업/조율", 1.5, "structural",
              "internal-* A2A 채널에서 양방향(서로 다른 화자 ≥2) 교류가 실제로 일어났는가"),
    Dimension("instruction_following", "지시 반영", 1.5, "judge",
              "각 라운드 산출물이 그 라운드의 오너 지시를 실제로 반영했는가"),
    Dimension("no_leaks", "누수 없음", 1.0, "structural",
              "메타(자기=AI 고백/시스템 syntax)·에러 마커 누수가 0 인가"),
]
_BY_KEY = {d.key: d for d in DIMENSIONS}


# ── transcript + channel helpers ─────────────────────────────────────────────────

COORDINATOR_DM = "dm-coordinator"
OWNER_REVIEW_CHANNEL = "internal-owner"


def _last_deliverable(snap: dict) -> str:
    """The core deliverable = drive_result.last_deliverable, falling back to the last
    coordinator synthesis in dm-coordinator (the same resolution ws_report uses)."""
    dr = snap.get("drive_result") or {}
    deliverables = ws_verdict._coordinator_deliverables(snap)
    return (dr.get("last_deliverable") or (deliverables[-1] if deliverables else "")) or ""


def _round_pairs(snap: dict, *, limit: int = 6) -> list[tuple[str, str]]:
    """(owner_instruction_k, deliverable_k) pairs, in round order, for the
    instruction-following judge. Owner instructions = the owner's messages in
    dm-coordinator; deliverables = the coordinator's synthesis messages there."""
    owner_id = snap.get("owner_id", "owner")
    coord_msgs = (snap.get("channels") or {}).get(COORDINATOR_DM, [])
    instrs = [(m.get("message") or "").strip() for m in coord_msgs
              if m.get("speaker") == owner_id and (m.get("message") or "").strip()]
    delivs = ws_verdict._coordinator_deliverables(snap)
    pairs = []
    for i in range(min(len(instrs), len(delivs), limit)):
        pairs.append((instrs[i], delivs[i]))
    return pairs


# ── structural dimension evaluators ──────────────────────────────────────────────

def _eval_task_decomposition(metrics: dict) -> DimResult:
    d = _BY_KEY["task_decomposition"]
    deleg = metrics.get("delegation_by_channel", {}) or {}
    if not deleg:
        return DimResult.for_dim(d, score=0.0, passed=False,
            detail="살아있는 전문가 DM 이 없음 — 팀 분해 미발생")
    covered = sum(1 for n in deleg.values() if (n or 0) >= 1)
    total = len(deleg)
    score = round(10.0 * covered / total, 1)
    return DimResult.for_dim(d, score=score, passed=(covered == total),
        detail=f"{covered}/{total} 전문가 채널에 코디네이터 위임 ({', '.join(sorted(deleg))})")


def _eval_deliverable_completeness(snap: dict, metrics: dict) -> DimResult:
    d = _BY_KEY["deliverable_completeness"]
    deliv = _last_deliverable(snap).strip()
    if not deliv or "[오류]" in deliv or "Traceback" in deliv:
        return DimResult.for_dim(d, score=0.0, passed=False,
            detail="핵심 산출물 없음/오류 — CRITICAL FAIL")
    long_enough = len(deliv) >= _DELIVERABLE_LEN_THRESHOLD
    structured = ws_verdict._has_structure(deliv)
    # 길이 + 구조 둘 다 충족 = 10, 하나만 = 6, 비었으면(위에서 처리) 0.
    if long_enough and structured:
        score, passed = 10.0, True
    elif long_enough or structured:
        score, passed = 6.0, False
    else:
        score, passed = 3.0, False
    return DimResult.for_dim(d, score=score, passed=passed,
        detail=f"{len(deliv)}자 · 구조 {'있음' if structured else '없음'}"
               + (" (완결)" if passed else " (보완 필요)"))


def _eval_coordination_quality(snap: dict, metrics: dict) -> DimResult:
    d = _BY_KEY["coordination_quality"]
    a2a = metrics.get("a2a_by_channel", {}) or {}        # {channel: {speaker: count}}
    min_each = int(metrics.get("a2a_min_each_required", 1) or 1)
    if not a2a:
        return DimResult.for_dim(d, score=0.0, passed=False,
            detail="A2A(internal-*) 채널이 없음 — 협업 흔적 없음")
    ok = 0
    for counts in a2a.values():
        qualifying = [sp for sp, n in (counts or {}).items() if (n or 0) >= min_each]
        if len(qualifying) >= 2:
            ok += 1
    total = len(a2a)
    score = round(10.0 * ok / total, 1)
    return DimResult.for_dim(d, score=score, passed=(ok == total),
        detail=f"{ok}/{total} A2A 채널에 양방향 교류 (서로 다른 화자 ≥2, 각 ≥{min_each})")


def _eval_no_leaks(metrics: dict) -> DimResult:
    d = _BY_KEY["no_leaks"]
    meta = int(metrics.get("meta_leaks", 0) or 0)
    err = int(metrics.get("error_leaks", 0) or 0)
    total = meta + err
    score = max(0.0, 10.0 - 3.0 * total)
    detail = (f"메타 {meta} · 에러 {err} = 총 {total} 누수"
              + (" (clean)" if total == 0 else ""))
    return DimResult.for_dim(d, score=score, passed=(total == 0), detail=detail)


# ── judge dimension evaluators ───────────────────────────────────────────────────

_INSTRUCTION_PROMPT = """너는 한 팀의 작업을 검수하는 채점자야. 매 라운드마다 오너가 지시를 주고,
팀(매니저)이 그 라운드의 결과물을 낸다. **각 라운드의 결과물이 그 라운드의 오너 지시를
실제로 반영했는지**만 본다. (말투·문체·길이는 평가 대상 아님 — 오직 지시 반영도.)

좋은 예: 오너가 "리스크 섹션을 추가하라"고 했고 결과물에 리스크가 새로 들어옴.
나쁜 예: 오너 지시를 무시하고 이전 라운드와 똑같은 내용을 반복, 지시한 항목이 결과물에 없음.

0~10 으로 채점. 10 = 모든 라운드가 지시를 충실히 반영, 0 = 지시를 전혀 반영 안 함.
엄격하게 JSON 만:
{{"score": 0-10, "pass": true|false, "rationale": "한 줄 (어떤 지시가 반영/무시됐는지)"}}
pass = score >= 7.

--- 라운드별 (오너 지시 → 결과물) ---
{pairs}
"""


def _eval_deliverable_quality(snap: dict, do_judge: bool,
                              min_score: int) -> DimResult:
    d = _BY_KEY["deliverable_quality"]
    if not do_judge:
        return DimResult.for_dim(d, score=None, passed=None,
            detail="echo / CLI 미존재 — judge 생략", skipped=True, skip_reason="no-judge")
    deliv = _last_deliverable(snap)
    q = ws_judge.judge_deliverable(
        deliverable=deliv, goal=snap.get("goal", ""),
        context=snap.get("context", ""), min_score=min_score)
    if q.get("status") != "scored" or q.get("overall") is None:
        return DimResult.for_dim(d, score=None, passed=None,
            detail=f"judge 실패: {q.get('rationale', '')[:80]}",
            skipped=True, skip_reason="judge-error")
    axes = " · ".join(f"{k} {v}" for k, v in (q.get("scores") or {}).items())
    return DimResult.for_dim(d, score=float(q["overall"]), passed=bool(q.get("pass")),
        detail=f"5축 [{axes}] — {q.get('rationale', '')[:120]}")


def _eval_instruction_following(snap: dict, do_judge: bool) -> DimResult:
    d = _BY_KEY["instruction_following"]
    if not do_judge:
        return DimResult.for_dim(d, score=None, passed=None,
            detail="echo / CLI 미존재 — judge 생략", skipped=True, skip_reason="no-judge")
    pairs = _round_pairs(snap)
    if not pairs:
        return DimResult.for_dim(d, score=None, passed=None,
            detail="오너 지시↔결과물 쌍 없음 — judge 생략", skipped=True, skip_reason="empty")
    rendered = "\n\n".join(
        f"[라운드 {i + 1}]\n오너 지시: {instr[:600]}\n결과물: {deliv[:1200]}"
        for i, (instr, deliv) in enumerate(pairs))
    raw = call_haiku(_INSTRUCTION_PROMPT.format(pairs=rendered), timeout=120)
    if not raw or raw.startswith("__ERROR__"):
        return DimResult.for_dim(d, score=None, passed=None,
            detail=f"judge 실패: {(raw or '')[:80]}", skipped=True, skip_reason="judge-error")
    data = extract_json(raw) or {}
    try:
        score = max(0.0, min(10.0, float(data.get("score"))))
    except (TypeError, ValueError):
        return DimResult.for_dim(d, score=None, passed=None,
            detail="judge 응답 파싱 실패", skipped=True, skip_reason="parse-error")
    passed = bool(data.get("pass")) if "pass" in data else score >= 7
    return DimResult.for_dim(d, score=score, passed=passed,
        detail=(data.get("rationale") or "").strip()[:120])


# ── public API ───────────────────────────────────────────────────────────────────

def assess(snap: dict, *, run_judges: Optional[bool] = None,
           min_overall: int = DEFAULT_MIN_OVERALL,
           deliverable_min: int = ws_judge.DEFAULT_MIN_SCORE) -> dict:
    """Full multi-dimension QA assessment of one Workspace run snapshot → a generation
    record dict (``glimi.edd.Assessment.as_dict()`` shape, plus Workspace meta).

    ``run_judges`` forces / skips the LLM-judge dimensions (default: auto — real
    backend AND the claude CLI present, mirroring ws_report/ws_judge).
    """
    verdict = ws_verdict.judge_snapshot(snap)
    metrics = verdict.get("metrics", {}) or {}

    backend = (snap.get("backend") or "echo").lower()
    if run_judges is None:
        run_judges = backend not in ("echo", "") and ws_judge.judge_available()

    results = [
        _eval_task_decomposition(metrics),
        _eval_deliverable_completeness(snap, metrics),
        _eval_deliverable_quality(snap, run_judges, deliverable_min),
        _eval_coordination_quality(snap, metrics),
        _eval_instruction_following(snap, run_judges),
        _eval_no_leaks(metrics),
    ]

    assessment = build_assessment(results, min_overall=min_overall, meta={
        "app": "workspace",
        "backend": backend,
        "judged": bool(run_judges),
        "structural_status": verdict.get("status"),
        "structural_verdict": verdict.get("verdict"),
        "judge_model": _JUDGE_MODEL,
    })
    return assessment.as_dict()
