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
  - coordinator_delegated  — the Coordinator spoke into every live specialist DM.
    The roster is DYNAMIC (the manager proposes a goal-fit team), so the verdict
    DERIVES the specialist DMs from the snapshot = every ``dm-*`` except
    ``dm-coordinator`` (dm-researcher/builder/critic is just the default team);
  - a2a_present            — every ``internal-*`` channel (except internal-owner)
    had ≥2 DISTINCT non-owner speakers, each with ≥ min_each messages
    (roster-agnostic bidirectional check from the messages, not the channel name);
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
# The roster is DYNAMIC — the manager proposes a goal-fit team, so the verdict
# DERIVES the delegation/A2A channels and specialist speakers from the snapshot
# (see _specialist_dms / _a2a_channels / _judged_speakers) instead of hardcoding
# a fixed roster. These constants document the DEFAULT team for reference only;
# they are NOT used to gate a run.
DEFAULT_DELEGATION_CHANNELS = ("dm-researcher", "dm-builder", "dm-critic")
DEFAULT_A2A_CHANNELS = ("internal-researcher-critic", "internal-builder-researcher")
DEFAULT_SPECIALISTS = ("researcher", "builder", "critic")

# Meta-leak scan. CRITICAL DOMAIN NOTE: the Workspace is a team *building/analyzing
# software*, so "AI", "에이전트"(agent), "봇"(bot), "인공지능", "페르소나"(user persona
# in UX!), "시뮬레이션"(env/test), "프롬프트"(shell prompt), "설계"(design) are ALL
# legitimate PRODUCT/market/architecture vocabulary — a human colleague says them
# constantly. So bare keywords are NOT leaks here (unlike the Community social-persona
# domain). We only flag (a) system-mechanic syntax a human would never emit, and
# (b) explicit SELF-reveal phrases where a speaker describes ITSELF as an AI/model.
META_PATTERNS = [
    "<tools>", "<call", "language model", "system prompt",
]
# Self-reveal phrases (speaker describing ITSELF as AI), distinct from discussing AI
# as a topic. e.g. "저는 AI라서", "as an AI", "언어모델로서" — real leaks.
_SELF_REVEAL = re.compile(
    r"(저는|제가|나는|난)\s*(인공지능|ai|언어\s*모델|챗?봇)\b"
    r"|\bas an ai\b|\bi'?m an ai\b|\bi am an ai\b"
    r"|(인공지능|ai|언어\s*모델)\s*(어시스턴트|모델)?\s*(이?라서|로서|로써|입니다|이에요|예요|이야)",
    re.I,
)

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
    # Headless runner stores ``ws-store-<ts>.json``; the web E2E harness
    # (ws_e2e) stores ``ws-e2e-store-<ts>.json`` and uses run-id ``ws-e2e-<ts>``.
    # Accept both so judge_run works on either artifact.
    if run_id.startswith("ws-e2e-"):
        ts = run_id[len("ws-e2e-"):]
        candidates = [RESULTS_DIR / f"ws-e2e-store-{ts}.json"]
    elif run_id.startswith("ws-run-"):
        ts = run_id[len("ws-run-"):]
        candidates = [RESULTS_DIR / f"ws-store-{ts}.json",
                      RESULTS_DIR / f"ws-e2e-store-{ts}.json"]
    else:
        ts = run_id
        candidates = [RESULTS_DIR / f"ws-store-{ts}.json",
                      RESULTS_DIR / f"ws-e2e-store-{ts}.json"]
    for store_path in candidates:
        if store_path.exists():
            return json.loads(store_path.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"store snapshot not found: tried {[str(c) for c in candidates]}")


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
    m = _SELF_REVEAL.search(text or "")
    if m:
        hits.append(f"self-reveal:{m.group(0)[:24]}")
    return hits


def _msgs(snap: dict, channel: str) -> list[dict]:
    return snap.get("channels", {}).get(channel, [])


def _by_speaker(msgs: list[dict], speaker: str) -> list[dict]:
    return [m for m in msgs if m.get("speaker") == speaker]


# ── the checks ─────────────────────────────────────────────────────────────────

_STRUCTURE_RE = re.compile(r"(^|\n)\s*(#{1,6}\s|[-*]\s|\d+\.\s|\d+\)\s)")


def _coordinator_deliverables(snap: dict) -> list[str]:
    """The REAL per-round coordinator deliverables = coordinator's own messages in
    dm-coordinator (the gated document synthesis), in order.

    The served-data E2E path synthesizes drive_result.deliverables from exactly
    these messages, but the headless path's drive_result is authoritative. We
    prefer the live dm-coordinator messages (works for both paths) and fall back
    to drive_result.deliverables only if dm-coordinator is empty.
    """
    coord_msgs = [(m.get("message") or "")
                  for m in _by_speaker(_msgs(snap, COORDINATOR_DM), "coordinator")]
    coord_msgs = [c for c in coord_msgs if c.strip()]
    if coord_msgs:
        return coord_msgs
    return [d for d in ((snap.get("drive_result") or {}).get("deliverables") or [])
            if (d or "").strip()]


def _check_deliverables(snap: dict, rounds: int, issues: list, metrics: dict):
    """Every round produced a non-empty Coordinator deliverable in dm-coordinator.

    The deliverable is the Coordinator's gated synthesis logged to dm-coordinator.
    The served-data E2E path has NO drive_result, so we measure the REAL
    deliverables directly = the coordinator's own messages in dm-coordinator. We
    assert they are all non-empty / error-free and that dm-coordinator carries
    Coordinator output.
    """
    deliverables = _coordinator_deliverables(snap)
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


def _specialist_dms(snap: dict) -> list[str]:
    """Live specialists' DM channels = every 'dm-*' EXCEPT 'dm-coordinator'.

    The roster is DYNAMIC: the manager proposes a goal-fit team, so the channels
    are whatever the manager built (dm-researcher/builder/critic in the default
    case, or dm-culture-coach/dm-dev-lead/… for a custom roster). We derive them
    from the snapshot instead of hardcoding the old fixed roster.
    """
    return sorted(ch for ch in snap.get("channels", {})
                  if ch.startswith("dm-") and ch != COORDINATOR_DM)


def _check_delegation(snap: dict, issues: list, metrics: dict):
    """Coordinator delegated to every live specialist (spoke into each dm-*).

    Roster-agnostic: every 'dm-*' channel except dm-coordinator is a specialist's
    DM (whatever the dynamic roster). A specialist DM is flagged only if the
    coordinator NEVER spoke into it. The default team (dm-researcher/builder/critic)
    is just the default case of this same rule.
    """
    deleg = {}
    for ch in _specialist_dms(snap):
        n = len(_by_speaker(_msgs(snap, ch), "coordinator"))
        deleg[ch] = n
        if n == 0:
            issues.append({"severity": "REGRESSION", "category": "delegation",
                           "detail": f"코디네이터가 {ch} 에 한 번도 위임 안 함"})
    metrics["delegation_by_channel"] = deleg


def _a2a_channels(snap: dict) -> list[str]:
    """Agent↔agent (A2A) channels = every 'internal-*' EXCEPT 'internal-owner'.

    Roster-agnostic: the manager names these after the actual pair it wired
    (internal-researcher-critic in the default team, internal-culture-coach-
    hr-designer / internal-dev-lead-culture-coach / … for a custom roster). We do
    NOT parse role ids out of the channel name — we count distinct speakers from
    the messages, so the check works for any roster.
    """
    return sorted(ch for ch in snap.get("channels", {})
                  if ch.startswith("internal-") and ch != OWNER_REVIEW_CHANNEL)


def _check_a2a(snap: dict, issues: list, metrics: dict):
    """Each internal-* A2A channel had genuine back-and-forth from BOTH participants.

    Roster-agnostic bidirectional check: for each internal-* channel (except
    internal-owner) require ≥2 DISTINCT non-owner speakers, each with ≥ min_each
    messages — derived from the messages, not from the channel name.

    Backend-aware threshold:
      - real backends (claude_cli / ollama) → ≥2 messages from each side (the
        spec's strict bar: a real exchange, not one-sided);
      - echo → ≥1 from each. The echo backend emits IDENTICAL text every turn, so
        the store's identical-row dedup collapses repeated turns to a single row;
        requiring 2 distinct identical rows is structurally impossible on echo and
        would falsely fail the free self-test. The structural truth (both
        participants spoke, on both internal channels) still holds.
    """
    backend = (snap.get("backend") or "echo").lower()
    min_each = 1 if backend == "echo" else 2
    owner_id = snap.get("owner_id", "owner")
    a2a = {}
    for ch in _a2a_channels(snap):
        counts: dict[str, int] = {}
        for m in _msgs(snap, ch):
            sp = m.get("speaker")
            if not sp or sp == owner_id:
                continue
            counts[sp] = counts.get(sp, 0) + 1
        a2a[ch] = counts
        qualifying = [sp for sp, n in counts.items() if n >= min_each]
        if len(qualifying) < 2:
            issues.append({"severity": "REGRESSION", "category": "a2a",
                           "detail": f"{ch}: 양방향 부족 ({counts}; 서로 다른 "
                                     f"화자 ≥2, 각 ≥{min_each} 기대, backend={backend})"})
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


def _judged_speakers(snap: dict) -> set:
    """All speakers whose messages we judge for leaks = coordinator + owner + the
    DYNAMIC roster's specialists (every distinct non-owner speaker that appears in
    a specialist DM or A2A channel). Roster-agnostic — no hardcoded role ids.
    """
    owner_id = snap.get("owner_id", "owner")
    speakers = {"coordinator", owner_id}
    channels = snap.get("channels", {})
    for ch in (*_specialist_dms(snap), *_a2a_channels(snap), "group-team"):
        for m in channels.get(ch, []):
            sp = m.get("speaker")
            if sp:
                speakers.add(sp)
    return speakers


def _check_meta_leaks(snap: dict, issues: list, metrics: dict):
    """Meta-keyword scan over ALL coordinator + specialist + owner messages."""
    judged_speakers = _judged_speakers(snap)
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
    # The runner-captured exception (if any). A wall-clock-cap timeout is a
    # runner-ENVELOPE condition (the harness stopped polling), NOT a defect in the
    # run's actual output — the served snapshot it captured may still be excellent.
    # Surface it as a soft DRIFT so the structural verdict reflects the captured
    # data; a genuine runner crash/traceback stays a BLOCKER.
    err = snap.get("error")
    metrics["runner_error"] = err
    if err:
        is_envelope = "wall_clock_cap" in err or "wall-clock" in err.lower()
        issues.append({
            "severity": "DRIFT" if is_envelope else "BLOCKER",
            "category": "runner_envelope" if is_envelope else "error",
            "detail": (f"runner 벽시계 캡 (envelope, soft): {err}" if is_envelope
                       else f"runner 예외: {err}"),
        })


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


_GOAL_LEN_THRESHOLD = 400  # chars: a substantial document, not a one-line ack


def _has_structure(text: str) -> bool:
    """Markdown structure = headings / bullet lists / numbered lists."""
    return bool(_STRUCTURE_RE.search(text or ""))


def _check_goal_advanced(snap: dict, issues: list, metrics: dict):
    """Soft heuristic: the goal advanced (a substantial, structured deliverable).

    Soft-warn, NEVER a hard fail — LLM variance. The served-data path has no
    drive_result, so we measure the REAL deliverable = the LONGEST coordinator
    message in dm-coordinator (the gated document synthesis), with round-
    representative lengths from the actual coordinator outputs (first substantive
    vs longest). Advanced when the final/longest deliverable is substantial (over
    a sane length threshold AND shows markdown structure), OR it meaningfully grew
    vs the first substantive output, OR the owner declared done with a non-trivial
    final deliverable.
    """
    deliverables = _coordinator_deliverables(snap)
    dr = snap.get("drive_result") or {}
    advanced = False
    detail = ""
    if deliverables:
        first = deliverables[0] or ""
        longest = max(deliverables, key=lambda d: len(d or "")) or ""
        metrics["deliverable_len_first"] = len(first)
        metrics["deliverable_len_last"] = len(longest)
        metrics["deliverable_has_structure"] = _has_structure(longest)
        substantial = len(longest) >= _GOAL_LEN_THRESHOLD and _has_structure(longest)
        grew = len(longest) >= len(first) * 1.5 and len(longest) > 200
        done_early = dr.get("done") and len(longest) > 40
        advanced = bool(substantial or grew or done_early)
        if not advanced:
            detail = (f"최종 결과물이 빈약 (first={len(first)}, longest={len(longest)}, "
                      f"structure={_has_structure(longest)}, done={dr.get('done')})")
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


def judge_snapshot(snap: dict, run_id: str = "ws-run-adhoc") -> dict:
    """Judge an already-loaded snapshot dict → verdict dict (no disk read).

    This is the storage-agnostic core: it runs the same eight checks the
    file-based :func:`judge_run` does, but on a snapshot that the caller already
    holds. The headless runner reads its ``ws-store-<ts>.json`` from disk via
    ``judge_run``; the web E2E harness (``tests.e2e.ws_e2e``) assembles the SAME
    snapshot shape from the SERVED HTTP endpoints and passes it straight here, so
    both paths reuse identical criteria. Does NOT persist — the caller decides.
    """
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
    return {
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


def judge_run(run_id: str) -> dict:
    """Judge a workspace run from its store snapshot → verdict dict, and persist it."""
    snap = _load_snapshot(run_id)
    verdict = judge_snapshot(snap, run_id=run_id)

    # Persist the judged verdict (overwrites the runner's provisional envelope),
    # matching the Community runner→analyze_run handoff. Headless → ws-run-<ts>.json;
    # web E2E → ws-e2e-<ts>.json (mirror the run-id family).
    if run_id.startswith("ws-e2e-"):
        out_path = RESULTS_DIR / f"{run_id}.json"
    else:
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
