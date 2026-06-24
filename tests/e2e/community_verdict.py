# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Community WEB E2E verdict — judge an owner↔friends chat run from a snapshot.

This is the Community analogue of :mod:`tests.e2e.ws_verdict`. Where the Workspace
verdict judges an autonomous coordinator loop (deliverable each round, delegation,
A2A), the Community deliverable is simpler and more human: **the owner messaged a
few AI friends in their DMs, and each friend actually replied — in character, with
no meta leaks and no errors.**

The harness (:mod:`tests.e2e.community_e2e`) drives the REAL served community
server over the chat WebSocket and assembles a flat snapshot from the SERVED HTTP
endpoints (``/chat/channels`` + ``/chat/history`` per DM + ``/api/usage``). This
module then judges that snapshot against:

  - friend_replied         — every DRIVEN DM got ≥1 non-empty friend reply (the
    core deliverable; a DM with an owner message but no friend reply = FAIL);
  - replies_distinct       — on a real backend, a friend's replies are not all the
    identical string (a stuck/looping reply); echo is exempt (echo emits the same
    text by design + the store dedups identical rows);
  - no_meta_leaks          — the COMMUNITY-domain meta scan (REUSES ws_verdict's
    ``_SELF_REVEAL`` self-reveal regex + adds bare social-persona keywords that a
    real friend would never say: "AI"/"에이전트"/"봇"/"언어모델"/"프롬프트"/<tools>).
    Unlike the Workspace (software-building domain, where "AI"/"agent" are normal
    product vocabulary), here a friend describing themselves or the chat in
    system/AI terms IS a leak;
  - no_errors              — no ``[오류]`` / ``Traceback`` / ``turn failed`` /
    ``CAPPED`` leaked into any chat channel;
  - owner_drove            — the owner actually posted ≥1 message into each driven
    DM (sanity: the harness really exercised the WS write path).

Emits ``{status, verdict, issues, metrics}`` — PASS / WARN / FAIL, same shape and
severity ladder (BLOCKER→FAIL, REGRESSION/DRIFT→WARN) as ws_verdict, so the two
verdicts read identically.

Usage::

    python -m tests.e2e.community_verdict                    # latest community-e2e
    python -m tests.e2e.community_verdict community-e2e-YYYYMMDD-HHMMSS
    python -m tests.e2e.community_verdict --pretty
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Reuse the Workspace verdict's self-reveal regex + error markers — they are
# domain-agnostic (a speaker calling ITSELF an AI is a leak everywhere; an error
# marker is an error everywhere). tests/e2e is importable (has __init__.py).
from tests.e2e.ws_verdict import _SELF_REVEAL, ERROR_MARKERS

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"

# COMMUNITY-DOMAIN meta scan. CRITICAL DOMAIN NOTE (the mirror of ws_verdict's
# note, INVERTED): the Community is a social space of human-feeling friends, so a
# friend must NEVER betray that they are software. Here the bare keywords ARE
# leaks (the opposite of the Workspace, where "AI"/"agent" are normal product
# vocabulary). A real friend simply never says "as an AI" / "내 프롬프트" / emits a
# <tools> block. We pair these literal markers with ws_verdict's _SELF_REVEAL
# regex (저는 AI라서 / as an AI / 언어모델로서 …).
META_PATTERNS = [
    "<tools>", "<call", "language model", "system prompt",
    "언어모델", "언어 모델", "프롬프트", "인공지능",
    "챗봇", "챗 봇", "as an ai", "i am an ai", "i'm an ai",
    "ai 어시스턴트", "ai assistant", "에이전트", "시뮬레이션",
]


# ── snapshot loading ───────────────────────────────────────────────────────────

def _resolve_run_id(arg: str | None) -> str:
    if arg:
        return arg
    stores = sorted(RESULTS_DIR.glob("community-e2e-store-*.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if stores:
        ts = stores[0].stem[len("community-e2e-store-"):]
        return f"community-e2e-{ts}"
    runs = sorted(RESULTS_DIR.glob("community-e2e-*.json"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if runs:
        return runs[0].stem
    sys.exit("no community-e2e-store-*.json / community-e2e-*.json in tests/e2e/results/")


def _load_snapshot(run_id: str) -> dict:
    ts = run_id[len("community-e2e-"):] if run_id.startswith("community-e2e-") else run_id
    store_path = RESULTS_DIR / f"community-e2e-store-{ts}.json"
    if store_path.exists():
        return json.loads(store_path.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"store snapshot not found: {store_path}")


# ── small helpers ────────────────────────────────────────────────────────────

def _meta_hits(text: str) -> list[str]:
    low = (text or "").lower()
    hits = [p for p in META_PATTERNS if p.lower() in low]
    m = _SELF_REVEAL.search(text or "")
    if m:
        hits.append(f"self-reveal:{m.group(0)[:24]}")
    return hits


def _msgs(snap: dict, channel: str) -> list[dict]:
    return snap.get("channels", {}).get(channel, [])


def _driven_dms(snap: dict) -> list[str]:
    """The DM channels the harness actually drove this run.

    The runner records the channels it sent owner messages into under
    ``driven_channels``; fall back to every ``dm-*`` channel present in the
    snapshot if the field is absent (older artifact)."""
    driven = snap.get("driven_channels")
    if driven:
        return [c for c in driven if c]
    return sorted(ch for ch in snap.get("channels", {}) if ch.startswith("dm-"))


def _friend_replies(snap: dict, channel: str) -> list[dict]:
    """Non-owner, non-empty messages in a DM = the friend's replies."""
    owner_id = snap.get("owner_id", "owner")
    return [m for m in _msgs(snap, channel)
            if m.get("speaker") and m.get("speaker") != owner_id
            and (m.get("message") or "").strip()]


def _owner_msgs(snap: dict, channel: str) -> list[dict]:
    owner_id = snap.get("owner_id", "owner")
    return [m for m in _msgs(snap, channel)
            if m.get("speaker") == owner_id or m.get("is_user")]


# ── the checks ─────────────────────────────────────────────────────────────────

def _check_owner_drove(snap: dict, issues: list, metrics: dict):
    """The owner actually posted into each driven DM (the WS write path ran)."""
    driven = _driven_dms(snap)
    metrics["driven_dms"] = driven
    owner_by_dm = {}
    for ch in driven:
        n = len(_owner_msgs(snap, ch))
        owner_by_dm[ch] = n
        if n == 0:
            issues.append({"severity": "BLOCKER", "category": "owner_drive",
                           "detail": f"{ch} 에 오너 발화가 하나도 없음 (WS 전송 실패 의심)"})
    metrics["owner_msgs_by_dm"] = owner_by_dm


def _check_friend_replied(snap: dict, issues: list, metrics: dict):
    """Every driven DM got at least one non-empty friend reply — the deliverable."""
    driven = _driven_dms(snap)
    replies_by_dm = {}
    for ch in driven:
        replies = _friend_replies(snap, ch)
        replies_by_dm[ch] = len(replies)
        if not replies:
            issues.append({"severity": "BLOCKER", "category": "no_reply",
                           "detail": f"{ch}: 친구가 한 번도 답하지 않음 (빈 대화)"})
    metrics["friend_replies_by_dm"] = replies_by_dm
    metrics["friend_replies_total"] = sum(replies_by_dm.values())


def _check_replies_distinct(snap: dict, issues: list, metrics: dict):
    """On a real backend, a friend's replies must not all be the identical string.

    Echo is exempt: echo emits ``(echo) You said: …`` deterministically and the
    store dedups identical rows, so an all-identical set is expected and benign on
    echo (same exemption rationale as ws_verdict's A2A echo carve-out)."""
    backend = (snap.get("backend") or "echo").lower()
    metrics["replies_distinct_checked"] = backend != "echo"
    if backend == "echo":
        return
    for ch in _driven_dms(snap):
        replies = [(m.get("message") or "").strip() for m in _friend_replies(snap, ch)]
        if len(replies) >= 2 and len(set(replies)) == 1:
            issues.append({"severity": "REGRESSION", "category": "stuck_reply",
                           "detail": f"{ch}: 친구 답변 {len(replies)}건이 전부 동일 "
                                     "(루프/고정 응답 의심)"})


def _check_meta_leaks(snap: dict, issues: list, metrics: dict):
    """Community-domain meta scan over ALL friend (non-owner) messages.

    Owner turns are NOT judged (the human can say anything). We scan every
    non-owner speaker in every channel — a friend revealing they are software
    anywhere is a regression."""
    owner_id = snap.get("owner_id", "owner")
    leaks = []
    for ch, msgs in snap.get("channels", {}).items():
        for m in msgs:
            sp = m.get("speaker")
            if not sp or sp == owner_id or m.get("is_user"):
                continue
            hits = _meta_hits(m.get("message", ""))
            if hits:
                leaks.append({"ch": ch, "speaker": sp,
                              "hits": sorted(set(hits)),
                              "snippet": (m.get("message", "") or "")[:140]})
    metrics["meta_leaks"] = len(leaks)
    if leaks:
        issues.append({"severity": "REGRESSION", "category": "meta_leak",
                       "detail": f"메타 용어 노출 {len(leaks)}건 (친구 발화에 AI/봇/프롬프트 등)",
                       "evidence": leaks[:4]})


def _check_owner_agent(snap: dict, issues: list, metrics: dict):
    """When an AUTONOMOUS OWNER AGENT drove the session, judge the OWNER side too —
    not just the friends. The owner is an LLM standing in for the human, so its
    turns must read as a real person: coherent, progressing across rounds, and with
    NO meta/AI-reveal leaks of its own.

    Only runs in ``drive_mode == "owner-agent"`` (the scripted path has no owner
    agent to judge). Checks:
      - owner_turns_produced  — the owner agent produced ≥1 turn (it actually drove);
      - owner_no_meta         — no owner turn leaks meta terms (AI/봇/프롬프트/…);
      - owner_progressed      — across ≥2 turns the owner didn't send the identical
        message every time (a stuck/looping owner). Echo is exempt (the scripted arc
        is deterministic and may legitimately repeat the friend-request fallback)."""
    if snap.get("drive_mode") != "owner-agent":
        metrics["owner_agent"] = False
        return
    metrics["owner_agent"] = True
    turns = snap.get("owner_turns") or []
    metrics["owner_turns"] = len(turns)

    if not turns:
        issues.append({"severity": "BLOCKER", "category": "owner_agent",
                       "detail": "오너 에이전트가 한 턴도 만들지 못함 (드라이브 실패)"})
        return

    # Owner-side meta scan (the owner must not betray it's software either).
    owner_leaks = []
    for t in turns:
        hits = _meta_hits(t.get("text", ""))
        if hits:
            owner_leaks.append({"channel": t.get("channel"),
                                "hits": sorted(set(hits)),
                                "snippet": (t.get("text", "") or "")[:140]})
    metrics["owner_meta_leaks"] = len(owner_leaks)
    if owner_leaks:
        issues.append({"severity": "REGRESSION", "category": "owner_meta_leak",
                       "detail": f"오너 에이전트 발화에 메타 용어 {len(owner_leaks)}건 "
                                 "(AI/봇/프롬프트 등 — 사람처럼 안 보임)",
                       "evidence": owner_leaks[:4]})

    # Owner progression — on a real backend the owner shouldn't send the SAME
    # message every round. Echo's scripted arc is deterministic → exempt.
    backend = (snap.get("backend") or "echo").lower()
    texts = [(t.get("text") or "").strip() for t in turns if (t.get("text") or "").strip()]
    metrics["owner_distinct_turns"] = len(set(texts))
    if backend != "echo" and len(texts) >= 2 and len(set(texts)) == 1:
        issues.append({"severity": "REGRESSION", "category": "owner_stuck",
                       "detail": f"오너 에이전트가 {len(texts)}턴 내내 같은 말만 함 (루프 의심)"})


def _check_errors(snap: dict, issues: list, metrics: dict):
    """No error/traceback/CAPPED leaked into any chat channel + surface a runner
    exception (a wall-clock cap is a soft envelope condition, not a defect)."""
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


# ── verdict ──────────────────────────────────────────────────────────────────

def _status_from_issues(issues: list) -> str:
    sev = {i["severity"] for i in issues}
    if "BLOCKER" in sev:
        return "FAIL"
    if sev:
        return "WARN"
    return "PASS"


def _verdict_line(status: str, issues: list) -> str:
    from collections import Counter
    sev = Counter(i["severity"] for i in issues)
    if status == "FAIL":
        return f"❌ FAIL — BLOCKER {sev.get('BLOCKER', 0)}건"
    if status == "WARN":
        return f"⚠️ WARN — {dict(sev)}"
    return "✅ PASS — 오너↔친구 채팅 정상 (모든 DM 응답·메타누수 없음)"


def judge_snapshot(snap: dict, run_id: str = "community-e2e-adhoc") -> dict:
    """Judge an already-loaded snapshot dict → verdict dict (no disk read).

    Storage-agnostic core: the web E2E harness assembles the snapshot from the
    SERVED HTTP endpoints and passes it straight here. Does NOT persist — the
    caller decides (mirrors ws_verdict.judge_snapshot)."""
    issues: list = []
    metrics: dict = {
        "backend": snap.get("backend"),
        "goal": snap.get("goal"),
    }

    _check_owner_drove(snap, issues, metrics)
    _check_friend_replied(snap, issues, metrics)
    _check_replies_distinct(snap, issues, metrics)
    _check_meta_leaks(snap, issues, metrics)
    _check_owner_agent(snap, issues, metrics)
    _check_errors(snap, issues, metrics)

    status = _status_from_issues(issues)
    return {
        "run_id": run_id,
        "status": status,
        "verdict": _verdict_line(status, issues),
        "backend": snap.get("backend"),
        "drive_mode": snap.get("drive_mode", "scripted"),
        "driven_dms": metrics.get("driven_dms", []),
        "friend_replies_total": metrics.get("friend_replies_total", 0),
        "owner_turns": metrics.get("owner_turns", 0),
        "elapsed_seconds": snap.get("elapsed_seconds"),
        "issues": issues,
        "metrics": metrics,
    }


def judge_run(run_id: str) -> dict:
    """Judge a community web E2E run from its store snapshot → verdict, and persist."""
    snap = _load_snapshot(run_id)
    verdict = judge_snapshot(snap, run_id=run_id)
    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Glimi Community web E2E verdict")
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
