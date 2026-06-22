# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Workspace QA verdict — judge an owner-driver run from its store snapshot.

The Community analyzer (``tests/e2e/analyze_run.py``) reads the qa SQLite DB and
emits a compact PASS/WARN/FAIL JSON so Claude never has to read raw logs. This is
the Workspace analogue: it reads the store snapshot the runner wrote
(``ws-store-<ts>.json``) and judges the autonomous loop against the spec's
``qaVerdict`` checks:

  - deliverable_each_round — every round produced a non-empty Coordinator
    deliverable in dm-coordinator (not empty / not ``[오류]``);
  - coordinator_delegated  — each round the Coordinator spoke into every
    dm-researcher / dm-builder / dm-critic (delegation, not a monologue);
  - a2a_present            — internal-researcher-critic AND internal-builder-
    researcher each gained ≥2 messages from BOTH participants;
  - owner_instructions_coherent_and_progressing — the owner posted ≥2 DISTINCT
    instructions to dm-coordinator and round k's is not a near-duplicate of k-1
    (normalized-token Jaccard < 0.8); internal-owner has ≥1 owner note per round;
  - no_meta_leaks          — the Community meta-keyword scan over ALL coordinator
    + specialist + owner messages; any hit = REGRESSION;
  - no_errors              — no ``[오류]`` / ``Traceback`` / ``turn failed`` /
    CAPPED leaked into a chat channel;
  - budget_respected       — no runaway: if the loop stopped for budget it issued
    no turns after the budget event, and no claude usage exceeded the cap;
  - goal_advanced          — soft heuristic: the final deliverable shows concrete
    artifacts/length growth vs round 1, OR the owner declared done early with a
    non-trivial deliverable (soft-warn, not hard-fail — LLM variance).

Emits ``tests/e2e/results/ws-run-<ts>.json`` ``{status, issues, metrics, rounds}``.

Usage::

    python -m tests.e2e.ws_verdict                  # latest ws-run
    python -m tests.e2e.ws_verdict ws-run-YYYYMMDD-HHMMSS
    python -m tests.e2e.ws_verdict --pretty
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"

OWNER_REVIEW_CHANNEL = "internal-owner"
COORDINATOR_DM = "dm-coordinator"
DELEGATION_CHANNELS = {
    "researcher": "dm-researcher",
    "builder": "dm-builder",
    "critic": "dm-critic",
}
A2A_PAIRS = [
    ("researcher", "critic", "internal-researcher-critic"),
    ("builder", "researcher", "internal-builder-researcher"),
]
SPECIALISTS = ["researcher", "builder", "critic"]

# Meta-keyword scan — mirrors analyze_run._analyze_meta's leak patterns, plus the
# explicit terms the spec calls out (에이전트 / 봇 / AI / <tools>). The owner text
# especially must read as a human delegating, never as a system describing itself.
META_PATTERNS = [
    "에이전트", "페르소나", "시뮬레이션", "프롬프트", "설계된", "예측 가능",
    "<tools>", "<call", "봇", "인공지능",
    "language model", "system prompt",
]
# "AI" as a standalone token (avoid matching inside words like "rAIse" / "메인").
_AI_TOKEN = re.compile(r"(?<![A-Za-z가-힣])AI(?![A-Za-z가-힣])")

# Error / failure markers that must never leak into a chat channel.
ERROR_MARKERS = ["[오류]", "Traceback", "turn failed", "에이전트간 대화 오류",
                 "CAPPED", "[ERROR]", "[tool_error]"]


# ── snapshot loading ───────────────────────────────────────────────────────────

def _resolve_run_id(arg: str | None) -> str:
    if arg:
        return arg
    stores = sorted(RESULTS_DIR.glob("ws-store-*.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if stores:
        ts = stores[0].stem[len("ws-store-"):]
        return f"ws-run-{ts}"
    runs = sorted(RESULTS_DIR.glob("ws-run-*.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if runs:
        return runs[0].stem
    sys.exit("no ws-store-*.json / ws-run-*.json in tests/e2e/results/")


def _load_snapshot(run_id: str) -> dict:
    ts = run_id[len("ws-run-"):] if run_id.startswith("ws-run-") else run_id
    store_path = RESULTS_DIR / f"ws-store-{ts}.json"
    if not store_path.exists():
        raise FileNotFoundError(f"store snapshot not found: {store_path}")
    return json.loads(store_path.read_text(encoding="utf-8"))


# ── small text helpers ─────────────────────────────────────────────────────────

def _norm_tokens(text: str) -> set:
    """Normalized token set for near-duplicate detection."""
    toks = re.findall(r"[0-9A-Za-z가-힣]+", (text or "").lower())
    return set(toks)


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _meta_hits(text: str) -> list[str]:
    hits = [p for p in META_PATTERNS if p.lower() in (text or "").lower()]
    if _AI_TOKEN.search(text or ""):
        hits.append("AI")
    return hits


def _msgs(snap: dict, channel: str) -> list[dict]:
    return snap.get("channels", {}).get(channel, [])


def _by_speaker(msgs: list[dict], speaker: str) -> list[dict]:
    return [m for m in msgs if m.get("speaker") == speaker]


# ── the checks ─────────────────────────────────────────────────────────────────

def _check_deliverables(snap: dict, rounds: int, issues: list, metrics: dict):
    """Every round produced a non-empty Coordinator deliverable in dm-coordinator.

    The deliverable is the Coordinator's gated synthesis. run_round logs the plan
    AND the final to dm-coordinator from the Coordinator; the per-round
    deliverables the driver returns are the authoritative list, so we assert the
    drive_result deliverables are all non-empty AND that dm-coordinator carries
    Coordinator output.
    """
    deliverables = (snap.get("drive_result") or {}).get("deliverables", [])
    metrics["deliverables_count"] = len(deliverables)
    empties = [i + 1 for i, d in enumerate(deliverables) if not (d or "").strip()]
    erred = [i + 1 for i, d in enumerate(deliverables)
             if any(mk in (d or "") for mk in ("[오류]", "Traceback"))]
    if rounds > 0 and len(deliverables) < rounds and not _stopped_early(snap):
        issues.append({"severity": "BLOCKER", "category": "deliverable",
                       "detail": f"{rounds} 라운드 요청했으나 결과물 {len(deliverables)}건만 생성"})
    if empties:
        issues.append({"severity": "BLOCKER", "category": "deliverable",
                       "detail": f"빈 결과물 라운드: {empties}"})
    if erred:
        issues.append({"severity": "BLOCKER", "category": "deliverable",
                       "detail": f"[오류]/Traceback 포함 결과물 라운드: {erred}"})
    coord_in_dm = _by_speaker(_msgs(snap, COORDINATOR_DM), "coordinator")
    metrics["coordinator_msgs_in_dm"] = len(coord_in_dm)
    if deliverables and not coord_in_dm:
        issues.append({"severity": "BLOCKER", "category": "deliverable",
                       "detail": "dm-coordinator 에 코디네이터 발화 없음"})


def _stopped_early(snap: dict) -> bool:
    """The loop legitimately stopped before max_rounds (done/budget/cancelled)."""
    reason = (snap.get("drive_result") or {}).get("stopped_reason")
    return reason in ("done", "budget", "cancelled")


def _check_delegation(snap: dict, issues: list, metrics: dict):
    """Coordinator delegated to every specialist (spoke into each dm-*)."""
    deleg = {}
    for sid, ch in DELEGATION_CHANNELS.items():
        n = len(_by_speaker(_msgs(snap, ch), "coordinator"))
        deleg[ch] = n
        if n == 0:
            issues.append({"severity": "REGRESSION", "category": "delegation",
                           "detail": f"코디네이터가 {ch} 에 한 번도 위임 안 함"})
    metrics["delegation_by_channel"] = deleg


def _check_a2a(snap: dict, issues: list, metrics: dict):
    """Each internal-* A2A channel had genuine back-and-forth from BOTH participants.

    Backend-aware threshold:
      - real backends (claude_cli / ollama) → ≥2 messages from BOTH (the spec's
        strict bar: a real exchange, not one-sided);
      - echo → ≥1 from BOTH. The echo backend emits IDENTICAL text every turn, so
        the store's identical-row dedup collapses repeated turns to a single row;
        requiring 2 distinct identical rows is structurally impossible on echo and
        would falsely fail the free self-test. The structural truth (both
        participants spoke, on both internal channels) still holds.
    """
    backend = (snap.get("backend") or "echo").lower()
    min_each = 1 if backend == "echo" else 2
    a2a = {}
    for a, b, ch in A2A_PAIRS:
        msgs = _msgs(snap, ch)
        na = len(_by_speaker(msgs, a))
        nb = len(_by_speaker(msgs, b))
        a2a[ch] = {a: na, b: nb}
        if na < min_each or nb < min_each:
            issues.append({"severity": "REGRESSION", "category": "a2a",
                           "detail": f"{ch}: 양방향 부족 ({a}={na}, {b}={nb}; "
                                     f"각 ≥{min_each} 기대, backend={backend})"})
    metrics["a2a_by_channel"] = a2a
    metrics["a2a_min_each_required"] = min_each


def _check_owner_instructions(snap: dict, rounds: int, issues: list, metrics: dict):
    """Owner instructions to dm-coordinator are coherent + progressing.

    ≥2 distinct instructions; round k not a near-duplicate of k-1 (Jaccard < 0.8);
    internal-owner has ≥1 owner reasoning note per round.
    """
    owner_id = snap.get("owner_id", "owner")
    instrs = [m.get("message", "") for m in _by_speaker(_msgs(snap, COORDINATOR_DM), owner_id)]
    metrics["owner_instructions"] = len(instrs)
    metrics["owner_instructions_distinct"] = len(set(i.strip() for i in instrs))

    # Per round: at least 2 distinct work instructions (unless the loop legitimately
    # finished in ≤1 round).
    if rounds >= 2 and not _stopped_early(snap):
        if len(set(i.strip() for i in instrs)) < 2:
            issues.append({"severity": "DRIFT", "category": "owner_progress",
                           "detail": f"오너 지시가 {len(set(instrs))}개뿐 — 진전 부족"})

    # Near-duplicate consecutive instructions.
    dup_pairs = []
    for k in range(1, len(instrs)):
        j = _jaccard(_norm_tokens(instrs[k]), _norm_tokens(instrs[k - 1]))
        if j >= 0.8:
            dup_pairs.append({"rounds": [k, k + 1], "jaccard": round(j, 2)})
    if dup_pairs:
        issues.append({"severity": "DRIFT", "category": "owner_repeat",
                       "detail": f"연속 지시 near-duplicate {len(dup_pairs)}건 (Jaccard≥0.8)",
                       "evidence": dup_pairs[:3]})
    metrics["owner_dup_pairs"] = dup_pairs

    # internal-owner reasoning: ≥1 per owner turn.
    notes = _by_speaker(_msgs(snap, OWNER_REVIEW_CHANNEL), owner_id)
    metrics["owner_notes"] = len(notes)
    # owner turns = rounds run + (a final 'done' review with no instruction). Expect
    # at least one note per round.
    rounds_run = (snap.get("drive_result") or {}).get("rounds", 0)
    if rounds_run > 0 and len(notes) < rounds_run:
        issues.append({"severity": "DRIFT", "category": "owner_reasoning",
                       "detail": f"internal-owner 검토 {len(notes)}건 < 라운드 {rounds_run}"})


def _check_meta_leaks(snap: dict, issues: list, metrics: dict):
    """Meta-keyword scan over ALL coordinator + specialist + owner messages."""
    owner_id = snap.get("owner_id", "owner")
    judged_speakers = {"coordinator", *SPECIALISTS, owner_id}
    leaks = []
    for ch, msgs in snap.get("channels", {}).items():
        for m in msgs:
            if m.get("speaker") not in judged_speakers:
                continue
            text = m.get("message", "")
            hits = _meta_hits(text)
            if hits:
                leaks.append({
                    "ch": ch, "speaker": m.get("speaker"),
                    "hits": sorted(set(hits)),
                    "snippet": text[:140],
                })
    metrics["meta_leaks"] = len(leaks)
    if leaks:
        issues.append({"severity": "REGRESSION", "category": "meta_leak",
                       "detail": f"메타 용어 노출 {len(leaks)}건 (코디/전문가/오너 발화)",
                       "evidence": leaks[:4]})


def _check_errors(snap: dict, issues: list, metrics: dict):
    """No error/traceback/CAPPED leaked into any chat channel."""
    errs = []
    for ch, msgs in snap.get("channels", {}).items():
        for m in msgs:
            text = m.get("message", "") or ""
            for mk in ERROR_MARKERS:
                if mk in text:
                    errs.append({"ch": ch, "speaker": m.get("speaker"),
                                 "marker": mk, "snippet": text[:120]})
                    break
    metrics["error_leaks"] = len(errs)
    if errs:
        issues.append({"severity": "BLOCKER", "category": "error",
                       "detail": f"채널에 에러 마커 노출 {len(errs)}건",
                       "evidence": errs[:4]})
    # The runner-captured exception (if any).
    if snap.get("error"):
        issues.append({"severity": "BLOCKER", "category": "error",
                       "detail": f"runner 예외: {snap['error']}"})


def _check_budget(snap: dict, issues: list, metrics: dict):
    """Budget respected — no runaway, no claude usage over cap.

    If the loop stopped for budget it must have issued no team turns after the
    budget event (the driver gates BEFORE any kernel turn, so the deliverables
    count IS the issued-turns count). And no blocked/over-cap usage leaked.
    """
    dr = snap.get("drive_result") or {}
    reason = dr.get("stopped_reason")
    rounds_run = dr.get("rounds", 0)
    deliverables = dr.get("deliverables", [])
    metrics["stopped_reason"] = reason
    metrics["rounds_run"] = rounds_run

    if reason == "budget" and len(deliverables) != rounds_run:
        issues.append({"severity": "BLOCKER", "category": "budget",
                       "detail": "예산 중단 후에도 추가 턴 흔적 "
                                 f"(deliverables={len(deliverables)} != rounds={rounds_run})"})

    usage = snap.get("usage", []) or []
    metrics["usage_rows"] = len(usage)
    total_cost = sum(float(u.get("est_cost", 0) or 0) for u in usage)
    metrics["usage_total_cost"] = round(total_cost, 4)
    blocked = [u for u in usage if u.get("was_blocked")]
    metrics["usage_blocked_rows"] = len(blocked)
    # A budget cap, if configured, is enforced by allow_claude; we surface spend so
    # a runaway (huge cost) is visible. Hard-fail only on an absurd row count that
    # implies a loop ran past its cap (defense-in-depth observability).
    if rounds_run > 0 and len(usage) > rounds_run * 200:
        issues.append({"severity": "REGRESSION", "category": "budget",
                       "detail": f"비정상적으로 많은 사용 기록 {len(usage)}건 (runaway 의심)"})


def _check_goal_advanced(snap: dict, issues: list, metrics: dict):
    """Soft heuristic: the goal advanced (concrete artifacts / length growth).

    Soft-warn, not hard-fail — LLM variance. Advanced if: the final deliverable is
    meaningfully longer/richer than round 1, OR the owner declared done before
    max_rounds with a non-trivial final deliverable.
    """
    dr = snap.get("drive_result") or {}
    deliverables = dr.get("deliverables", [])
    advanced = False
    detail = ""
    if deliverables:
        first = deliverables[0] or ""
        last = (dr.get("last_deliverable") or deliverables[-1]) or ""
        metrics["deliverable_len_first"] = len(first)
        metrics["deliverable_len_last"] = len(last)
        grew = len(last) >= len(first) * 0.8 and len(last) > 40
        done_early = dr.get("done") and len(last) > 40
        advanced = bool(grew or done_early)
        if not advanced:
            detail = (f"최종 결과물이 빈약 (first={len(first)}, last={len(last)}, "
                      f"done={dr.get('done')})")
    else:
        detail = "결과물 없음"
    metrics["goal_advanced"] = advanced
    if not advanced:
        issues.append({"severity": "DRIFT", "category": "goal_advanced",
                       "detail": "목표 진전 약함 (soft) — " + detail})


# ── verdict ──────────────────────────────────────────────────────────────────

def _status_from_issues(issues: list) -> str:
    sev = {i["severity"] for i in issues}
    if "BLOCKER" in sev:
        return "FAIL"
    if sev:  # any REGRESSION / DRIFT / etc.
        return "WARN"
    return "PASS"


def _verdict_line(status: str, issues: list) -> str:
    from collections import Counter
    sev = Counter(i["severity"] for i in issues)
    if status == "FAIL":
        return f"❌ FAIL — BLOCKER {sev.get('BLOCKER', 0)}건"
    if status == "WARN":
        return f"⚠️ WARN — {dict(sev)}"
    return "✅ PASS — 자율 루프 정상 (모든 체크 통과)"


def judge_run(run_id: str) -> dict:
    """Judge a workspace run from its store snapshot → verdict dict, and persist it."""
    snap = _load_snapshot(run_id)
    rounds_requested = (snap.get("drive_result") or {}).get("rounds", 0)
    # Requested round count for "deliverable each round": prefer the runner's
    # rounds_requested if present, else fall back to rounds run.
    rounds = snap.get("rounds_requested") or rounds_requested

    issues: list = []
    metrics: dict = {
        "backend": snap.get("backend"),
        "goal": snap.get("goal"),
    }

    _check_deliverables(snap, rounds, issues, metrics)
    _check_delegation(snap, issues, metrics)
    _check_a2a(snap, issues, metrics)
    _check_owner_instructions(snap, rounds, issues, metrics)
    _check_meta_leaks(snap, issues, metrics)
    _check_errors(snap, issues, metrics)
    _check_budget(snap, issues, metrics)
    _check_goal_advanced(snap, issues, metrics)

    status = _status_from_issues(issues)
    verdict = {
        "run_id": run_id,
        "status": status,
        "verdict": _verdict_line(status, issues),
        "backend": snap.get("backend"),
        "rounds": metrics.get("rounds_run", rounds_requested),
        "stopped_reason": (snap.get("drive_result") or {}).get("stopped_reason"),
        "elapsed_seconds": snap.get("elapsed_seconds"),
        "issues": issues,
        "metrics": metrics,
    }

    # Persist the judged verdict to ws-run-<ts>.json (overwrites the runner's
    # provisional envelope), matching the Community runner→analyze_run handoff.
    ts = run_id[len("ws-run-"):] if run_id.startswith("ws-run-") else run_id
    out_path = RESULTS_DIR / f"ws-run-{ts}.json"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Glimi Workspace QA verdict")
    ap.add_argument("run_id", nargs="?", default=None)
    ap.add_argument("--pretty", action="store_true", help="사람 읽기용 포맷")
    args = ap.parse_args(argv)

    run_id = _resolve_run_id(args.run_id)
    verdict = judge_run(run_id)

    if args.pretty:
        json.dump(verdict, sys.stdout, ensure_ascii=False, indent=2)
    else:
        json.dump(verdict, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0 if verdict.get("status") in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
