# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Community PORTFOLIO report — a presentable Markdown summary of a chat run.

The Community analogue of :mod:`tests.e2e.ws_report`. The show-a-hiring-manager
artifact: one clean Markdown page that answers "did the owner's AI friends reply
like real friends, and what did it cost?" — quality score + rationale, cost,
latency, friend replies per DM, the pass criteria, and the trend vs baseline.

It consumes the consolidated metrics object (``community_metrics.build_metrics``) —
pure presentation over already-computed numbers — and writes a matched pair:

    tests/e2e/results/community-report-<ts>.md     (the page)
    tests/e2e/results/community-report-<ts>.json   (the metrics behind it)

REUSE: the trend block, the cost source line, and the status badge are taken
verbatim from ws_report (app-agnostic); only the quality rubric (friend
conversation vs work deliverable) and the structure section differ. On echo the
quality section honestly reads ``judge: skipped (echo)``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tests.e2e import community_judge, community_metrics
# Reuse the app-agnostic presentation helpers from ws_report (badge + trend block).
from tests.e2e.ws_report import _badge, _trend_block

RESULTS_DIR = community_metrics.RESULTS_DIR


def _quality_block(q: dict) -> list[str]:
    """Quality section — mirrors ws_report._quality_block but renders the COMMUNITY
    conversation rubric (community_judge.RUBRIC_AXES) instead of the deliverable one."""
    lines: list[str] = []
    status = q.get("status")
    if status == "skipped":
        lines.append(f"- **judge: skipped** — {q.get('rationale', 'judge skipped')}")
        lines.append("  - (LLM judge runs only on a real backend; echo is deterministic $0)")
        return lines
    if status == "error":
        lines.append(f"- **judge: error** — {q.get('rationale', 'judge call failed')}")
        return lines
    overall = q.get("overall")
    mark = "✅" if q.get("pass") else "❌"
    lines.append(f"- **Overall: {overall}/10 {mark}** "
                 f"(pass bar ≥ {q.get('min_score')})  · model `{q.get('model')}`")
    scores = q.get("scores") or {}
    if scores:
        lines.append("")
        lines.append("  | axis | score | what it measures |")
        lines.append("  | --- | --- | --- |")
        for axis, desc in community_judge.RUBRIC_AXES.items():
            sc = scores.get(axis)
            sc_s = f"{sc}/10" if sc is not None else "—"
            lines.append(f"  | {axis} | {sc_s} | {desc} |")
    if q.get("rationale"):
        lines.append("")
        lines.append(f"  > {q['rationale']}")
    return lines


def render_markdown(metrics: dict, trend: Optional[dict] = None) -> str:
    s = metrics["structure"]
    cost = metrics["cost"]
    lat = metrics["latency"]
    pc = metrics["pass_criteria"]
    v = metrics["verdict"]

    overall_emoji = "✅" if pc.get("overall_ok") else "❌"
    L: list[str] = []
    L.append("# Glimi Community — Chat Run Report")
    L.append("")
    L.append(f"**{overall_emoji} Overall: {'PASS' if pc.get('overall_ok') else 'FAIL'}**  ·  "
             f"backend `{metrics.get('backend')}`  ·  "
             f"{metrics.get('generated_at', '')[:19]}Z")
    L.append("")
    L.append(f"> **Scenario:** {metrics.get('goal') or '(none)'}")
    if metrics.get("context"):
        L.append(">")
        L.append(f"> **Context:** {metrics['context']}")
    L.append("")

    # ── Conversation quality ──
    L.append("## Conversation quality")
    L.append("")
    L.extend(_quality_block(metrics["quality"]))
    L.append("")

    # ── Owner ↔ friends (structure) ──
    L.append("## Owner ↔ friends")
    L.append("")
    # verdict_line already carries its own "<emoji> STATUS — " prefix; strip it so
    # the bolded badge isn't duplicated (e.g. "✅ PASS — ✅ PASS — …").
    _vline = v.get("verdict_line", "") or ""
    _vline = _vline.split(" — ", 1)[1] if " — " in _vline else _vline
    L.append(f"- Structural verdict: **{_badge(v.get('status'))}** — {_vline}")
    L.append(f"- DMs driven: **{s.get('driven_dm_count')}** "
             f"({s.get('dms_with_reply')} got a friend reply)")
    L.append(f"- Friend replies total: **{s.get('friend_replies_total')}**")
    replies = s.get("friend_replies_by_dm") or {}
    if replies:
        L.append("")
        L.append("  | DM channel | owner msgs | friend replies |")
        L.append("  | --- | --- | --- |")
        owner = s.get("owner_msgs_by_dm") or {}
        for ch, n in replies.items():
            L.append(f"  | `{ch}` | {owner.get(ch, 0)} | {n} |")
    L.append("")
    L.append(f"- Meta leaks: **{s.get('meta_leaks')}**  ·  Error leaks: **{s.get('error_leaks')}**")
    if v.get("issues"):
        L.append("")
        L.append("  <details><summary>issues</summary>")
        L.append("")
        for i in v["issues"]:
            L.append(f"  - `{i.get('severity')}` / {i.get('category')}: {i.get('detail')}")
        L.append("")
        L.append("  </details>")
    L.append("")

    # ── Cost & latency ──
    L.append("## Cost & latency")
    L.append("")
    est = f" ({cost.get('estimated_count')} estimated)" if cost.get("estimated_count") else ""
    L.append(f"- Spend: **${cost.get('total_usd', 0):.4f}**  ·  "
             f"{cost.get('call_count', 0)} LLM calls{est}  ·  source `{cost.get('source')}`")
    L.append(f"- Tokens: {cost.get('input_tokens', 0):,} in / "
             f"{cost.get('output_tokens', 0):,} out")
    L.append(f"- Latency: avg **{lat.get('avg_ms', 0)} ms**/call  ·  "
             f"wall **{lat.get('seconds_wall')} s**")
    by_agent = metrics.get("by_agent") or []
    if by_agent:
        L.append("")
        L.append("  | agent | model | calls | cost |")
        L.append("  | --- | --- | --- | --- |")
        for a in by_agent:
            L.append(f"  | {a.get('agent_id') or '?'} | `{a.get('model') or '—'}` | "
                     f"{a.get('call_count', 0)} | ${float(a.get('total_cost', 0)):.4f} |")
    L.append("")

    # ── Pass criteria ──
    L.append("## Pass criteria")
    L.append("")
    def _ck(ok: Any) -> str:
        return "✅" if ok is True else ("❌" if ok is False else "— (n/a)")
    L.append(f"- {_ck(pc.get('structural_ok'))} Structural verdict not FAIL")
    if pc.get("quality_judged"):
        L.append(f"- {_ck(pc.get('quality_ok'))} Conversation quality ≥ pass bar")
    else:
        L.append("- — Conversation quality (judge skipped — not counted)")
    L.append(f"- {_ck(pc.get('overall_ok'))} **Overall**")
    L.append("")

    # ── Trend vs baseline ── (reused verbatim from ws_report)
    L.append("## Trend vs baseline")
    L.append("")
    L.extend(_trend_block(trend))
    L.append("")
    L.append("---")
    L.append(f"_run_id `{metrics.get('run_id')}` · generated by `tests.e2e.community_report`_")
    L.append("")
    return "\n".join(L)


def write_report(metrics: dict, trend: Optional[dict] = None, *,
                 ts: Optional[str] = None,
                 results_dir: Optional[Path] = None) -> dict:
    """Render + write the .md page and the .json metrics. Returns the paths."""
    out_dir = Path(results_dir) if results_dir else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = ts or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    md_path = out_dir / f"community-report-{ts}.md"
    json_path = out_dir / f"community-report-{ts}.json"

    md_path.write_text(render_markdown(metrics, trend), encoding="utf-8")
    json_path.write_text(json.dumps({"metrics": metrics, "trend": trend},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    return {"md": str(md_path), "json": str(json_path), "ts": ts}


# ── orchestration: snapshot → judge → metrics → trend → report ───────────────────

def _transcript_from_snapshot(snap: dict) -> str:
    """Build a readable owner↔friends transcript (driven DMs, in id order) for the
    conversation judge. Uses display names when present, else speaker ids."""
    owner_id = snap.get("owner_id", "owner")
    owner_name = snap.get("owner_name") or "오너"
    driven = snap.get("driven_channels") or sorted(
        ch for ch in snap.get("channels", {}) if ch.startswith("dm-"))
    blocks: list[str] = []
    for ch in driven:
        rows = sorted(snap.get("channels", {}).get(ch, []),
                      key=lambda m: (m.get("id") or 0))
        if not rows:
            continue
        lines = [f"### {ch}"]
        for m in rows:
            sp = m.get("speaker")
            who = owner_name if (sp == owner_id or m.get("is_user")) else (sp or "?")
            lines.append(f"{who}: {(m.get('message') or '').strip()}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def generate_from_snapshot(snap: dict, *, run_id: str,
                           run_judge: Optional[bool] = None,
                           write_baseline: bool = False,
                           baseline_path: Optional[Path] = None,
                           min_score: int = community_judge.DEFAULT_MIN_SCORE,
                           results_dir: Optional[Path] = None) -> dict:
    """End-to-end report from a runner snapshot dict.

    1. Decide whether to judge (auto: real backend AND CLI present AND not echo).
    2. Score the owner↔friends transcript with ``community_judge``.
    3. Build consolidated metrics (``community_metrics.build_metrics``).
    4. Compare to the committed baseline (if any) for the trend.
    5. Render + write the report pair. Optionally (re)write the baseline.

    Returns ``{report_paths, metrics, quality, trend}``."""
    backend = (snap.get("backend") or "echo").lower()
    if run_judge is None:
        run_judge = backend not in ("echo", "") and community_judge.judge_available()

    transcript = _transcript_from_snapshot(snap)
    if run_judge and transcript.strip():
        quality = community_judge.judge_conversation(
            transcript=transcript, goal=snap.get("goal", ""),
            context=snap.get("context", ""), min_score=min_score,
        )
    else:
        reason = "echo" if backend in ("echo", "") else (
            "no transcript" if not transcript.strip() else "claude CLI not on PATH")
        quality = community_judge.skipped(reason, min_score=min_score)

    metrics = community_metrics.build_metrics(snap, run_id=run_id, quality=quality)

    baseline = community_metrics.load_baseline(baseline_path)
    trend = community_metrics.compare_to_baseline(metrics, baseline) if baseline else None

    paths = write_report(metrics, trend, results_dir=results_dir)

    if write_baseline:
        bp = community_metrics.write_baseline(metrics, baseline_path)
        paths["baseline"] = str(bp)

    return {"report_paths": paths, "metrics": metrics, "quality": quality,
            "trend": trend}


def _load_snapshot(snapshot_path: Path) -> tuple[dict, str]:
    snap = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    rid = snap.get("run_id")
    if not rid:
        rid = Path(snapshot_path).stem.replace("community-e2e-store-", "community-e2e-")
    return snap, rid


def _latest_snapshot() -> Optional[Path]:
    cands = list(RESULTS_DIR.glob("community-e2e-store-*.json"))
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Generate a portfolio report from a Community web E2E snapshot.")
    ap.add_argument("snapshot", nargs="?", default=None,
                    help="path to a community-e2e-store-*.json (default: latest)")
    ap.add_argument("--judge", dest="judge", action="store_true", default=None,
                    help="force-run the LLM judge (default: auto on real backend)")
    ap.add_argument("--no-judge", dest="judge", action="store_false",
                    help="skip the LLM judge even on a real backend")
    ap.add_argument("--write-baseline", action="store_true",
                    help="(re)write tests/e2e/community-baseline.json from this run")
    ap.add_argument("--min-score", type=int, default=community_judge.DEFAULT_MIN_SCORE,
                    help=f"quality pass bar (default {community_judge.DEFAULT_MIN_SCORE})")
    args = ap.parse_args(argv)

    snap_path = Path(args.snapshot) if args.snapshot else _latest_snapshot()
    if not snap_path or not snap_path.exists():
        print("no snapshot found — run tests.e2e.community_e2e first")
        return 2

    snap, run_id = _load_snapshot(snap_path)
    out = generate_from_snapshot(
        snap, run_id=run_id, run_judge=args.judge,
        write_baseline=args.write_baseline, min_score=args.min_score,
    )
    m = out["metrics"]
    q = out["quality"]
    print(f"\nGlimi Community report — backend={m['backend']} run_id={run_id}")
    print(f"  structural: {m['verdict']['status']}")
    if q.get("status") == "scored":
        print(f"  quality:    {q.get('overall')}/10 ({'pass' if q.get('pass') else 'fail'})")
    else:
        print(f"  quality:    {q.get('status')} ({q.get('reason', q.get('rationale', ''))})")
    print(f"  cost:       ${m['cost']['total_usd']:.4f} ({m['cost']['call_count']} calls)")
    print(f"  overall:    {'PASS' if m['pass_criteria']['overall_ok'] else 'FAIL'}")
    if out["trend"]:
        print(f"  trend:      {'no regression' if out['trend']['ok'] else 'REGRESSION'}")
    print(f"\n  report: {out['report_paths']['md']}")
    print(f"  metrics: {out['report_paths']['json']}")
    if out["report_paths"].get("baseline"):
        print(f"  baseline written: {out['report_paths']['baseline']}")
    return 0 if m["pass_criteria"]["overall_ok"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
