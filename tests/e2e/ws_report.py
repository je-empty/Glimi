# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Workspace PORTFOLIO report — a presentable Markdown summary of a run.

This is the show-a-hiring-manager artifact: one clean Markdown page that answers,
at a glance, "did the autonomous team produce a good deliverable, and what did it
cost?" — quality score + rationale, cost, latency, rounds, delegation/A2A, the
pass criteria, and the trend vs the committed baseline.

It consumes the consolidated metrics object (``ws_metrics.build_metrics``) — so the
report is pure presentation over already-computed numbers (no judging here) — and
writes a matched pair:

    tests/e2e/results/ws-report-<ts>.md     (the page)
    tests/e2e/results/ws-report-<ts>.json   (the metrics behind it)

On echo the quality section honestly reads ``judge: skipped (echo)`` rather than a
fabricated score.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tests.e2e import ws_judge, ws_metrics

RESULTS_DIR = ws_metrics.RESULTS_DIR


def _badge(status: str) -> str:
    return {"PASS": "✅ PASS", "WARN": "⚠️ WARN", "FAIL": "❌ FAIL"}.get(status, status or "?")


def _quality_block(q: dict) -> list[str]:
    lines: list[str] = []
    status = q.get("status")
    if status == "skipped":
        reason = q.get("rationale", "judge skipped")
        lines.append(f"- **judge: skipped** — {reason}")
        lines.append("  - (LLM judge runs only on a real backend; echo is deterministic $0)")
        return lines
    if status == "error":
        lines.append(f"- **judge: error** — {q.get('rationale', 'judge call failed')}")
        return lines
    overall = q.get("overall")
    passed = q.get("pass")
    mark = "✅" if passed else "❌"
    lines.append(f"- **Overall: {overall}/10 {mark}** "
                 f"(pass bar ≥ {q.get('min_score')})  · model `{q.get('model')}`")
    scores = q.get("scores") or {}
    if scores:
        lines.append("")
        lines.append("  | axis | score | what it measures |")
        lines.append("  | --- | --- | --- |")
        for axis, desc in ws_judge.RUBRIC_AXES.items():
            sc = scores.get(axis)
            sc_s = f"{sc}/10" if sc is not None else "—"
            lines.append(f"  | {axis} | {sc_s} | {desc} |")
    if q.get("rationale"):
        lines.append("")
        lines.append(f"  > {q['rationale']}")
    return lines


def _trend_block(trend: Optional[dict]) -> list[str]:
    if not trend:
        return ["- _no baseline committed yet — this run can seed one "
                "(`--write-baseline`)._"]
    lines: list[str] = []
    verdict = "✅ no regression" if trend.get("ok") else "❌ REGRESSION"
    lines.append(f"- **{verdict}** vs baseline "
                 f"(`{trend.get('baseline_backend')}`, {trend.get('baseline_generated_at', '?')})")
    for r in trend.get("regressions", []):
        lines.append(f"  - ❌ {r}")
    for n in trend.get("notes", []):
        lines.append(f"  - {n}")
    return lines


def render_markdown(metrics: dict, trend: Optional[dict] = None) -> str:
    s = metrics["structure"]
    cost = metrics["cost"]
    lat = metrics["latency"]
    pc = metrics["pass_criteria"]
    v = metrics["verdict"]

    overall_emoji = "✅" if pc.get("overall_ok") else "❌"
    L: list[str] = []
    L.append(f"# Glimi Workspace — Run Report")
    L.append("")
    L.append(f"**{overall_emoji} Overall: {'PASS' if pc.get('overall_ok') else 'FAIL'}**  ·  "
             f"backend `{metrics.get('backend')}`  ·  "
             f"{metrics.get('generated_at', '')[:19]}Z")
    L.append("")
    L.append(f"> **Goal:** {metrics.get('goal') or '(none)'}")
    if metrics.get("context"):
        L.append(f">")
        L.append(f"> **Context:** {metrics['context']}")
    L.append("")

    # ── Deliverable quality ──
    L.append("## Deliverable quality")
    L.append("")
    L.extend(_quality_block(metrics["quality"]))
    L.append("")

    # ── Autonomous loop (structure) ──
    L.append("## Autonomous loop")
    L.append("")
    L.append(f"- Structural verdict: **{_badge(v.get('status'))}** — {v.get('verdict_line', '')}")
    L.append(f"- Rounds run: **{s.get('rounds_run')}** "
             f"(stopped: `{s.get('stopped_reason')}`)")
    L.append(f"- Deliverables: **{s.get('deliverables_count')}** "
             f"(last {s.get('deliverable_len_last')} chars, "
             f"first {s.get('deliverable_len_first')})")
    L.append(f"- Delegation: manager spoke into **{s.get('delegation_channels_hit')}/3** "
             f"specialist channels")
    L.append(f"- Agent↔agent (A2A): **{s.get('a2a_channels_both_spoke')}/2** "
             f"internal channels had both sides speak")
    L.append(f"- Distinct owner instructions: **{s.get('owner_instructions_distinct')}**")
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
        L.append(f"- {_ck(pc.get('quality_ok'))} Deliverable quality ≥ pass bar")
    else:
        L.append(f"- — Deliverable quality (judge skipped — not counted)")
    L.append(f"- {_ck(pc.get('overall_ok'))} **Overall**")
    L.append("")

    # ── Trend vs baseline ──
    L.append("## Trend vs baseline")
    L.append("")
    L.extend(_trend_block(trend))
    L.append("")
    L.append("---")
    L.append(f"_run_id `{metrics.get('run_id')}` · generated by "
             f"`tests.e2e.ws_report`_")
    L.append("")
    return "\n".join(L)


def write_report(metrics: dict, trend: Optional[dict] = None, *,
                 ts: Optional[str] = None,
                 results_dir: Optional[Path] = None) -> dict:
    """Render + write the .md page and the .json metrics. Returns the paths."""
    out_dir = Path(results_dir) if results_dir else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = ts or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    md_path = out_dir / f"ws-report-{ts}.md"
    json_path = out_dir / f"ws-report-{ts}.json"

    payload = {"metrics": metrics, "trend": trend}
    md_path.write_text(render_markdown(metrics, trend), encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return {"md": str(md_path), "json": str(json_path), "ts": ts}


# ── orchestration: snapshot → judge → metrics → trend → report ───────────────────

def generate_from_snapshot(snap: dict, *, run_id: str,
                           run_judge: Optional[bool] = None,
                           write_baseline: bool = False,
                           baseline_path: Optional[Path] = None,
                           min_score: int = ws_judge.DEFAULT_MIN_SCORE,
                           results_dir: Optional[Path] = None) -> dict:
    """End-to-end report from a runner snapshot dict.

    1. Decide whether to judge: ``run_judge`` None → auto (real backend AND CLI
       present AND not echo). echo → SKIP cleanly (status 'skipped (echo)').
    2. Score the LAST deliverable (the owner-facing one) with ``ws_judge``.
    3. Build the consolidated metrics (``ws_metrics.build_metrics``).
    4. Compare to the committed baseline (if any) for the trend.
    5. Render + write the report pair. Optionally (re)write the baseline.

    Returns ``{report_paths, metrics, quality, trend}``.
    """
    backend = (snap.get("backend") or "echo").lower()
    if run_judge is None:
        run_judge = backend not in ("echo", "") and ws_judge.judge_available()

    dr = snap.get("drive_result") or {}
    deliverables = dr.get("deliverables") or []
    last = dr.get("last_deliverable") or (deliverables[-1] if deliverables else "")

    if run_judge and (last or "").strip():
        quality = ws_judge.judge_deliverable(
            deliverable=last, goal=snap.get("goal", ""),
            context=snap.get("context", ""), min_score=min_score,
        )
    else:
        reason = "echo" if backend in ("echo", "") else (
            "no deliverable" if not (last or "").strip()
            else "claude CLI not on PATH")
        quality = ws_judge.skipped(reason, min_score=min_score)

    metrics = ws_metrics.build_metrics(snap, run_id=run_id, quality=quality)

    baseline = ws_metrics.load_baseline(baseline_path)
    trend = ws_metrics.compare_to_baseline(metrics, baseline) if baseline else None

    paths = write_report(metrics, trend, results_dir=results_dir)

    if write_baseline:
        bp = ws_metrics.write_baseline(metrics, baseline_path)
        paths["baseline"] = str(bp)

    return {"report_paths": paths, "metrics": metrics, "quality": quality,
            "trend": trend}


def _load_snapshot(snapshot_path: Path) -> tuple[dict, str]:
    """Load a runner snapshot (ws-store-*.json or ws-e2e-store-*.json) + derive run_id."""
    snap = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    rid = snap.get("run_id")
    if not rid:
        stem = Path(snapshot_path).stem
        rid = stem.replace("ws-store-", "ws-run-").replace("ws-e2e-store-", "ws-e2e-")
    return snap, rid


def _latest_snapshot() -> Optional[Path]:
    cands = (list(RESULTS_DIR.glob("ws-store-*.json"))
             + list(RESULTS_DIR.glob("ws-e2e-store-*.json")))
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Generate a portfolio report from a Workspace run snapshot.")
    ap.add_argument("snapshot", nargs="?", default=None,
                    help="path to a ws-store-*.json / ws-e2e-store-*.json "
                         "(default: latest in results/)")
    ap.add_argument("--judge", dest="judge", action="store_true", default=None,
                    help="force-run the LLM judge (default: auto on real backend)")
    ap.add_argument("--no-judge", dest="judge", action="store_false",
                    help="skip the LLM judge even on a real backend")
    ap.add_argument("--write-baseline", action="store_true",
                    help="(re)write tests/e2e/ws-baseline.json from this run")
    ap.add_argument("--min-score", type=int, default=ws_judge.DEFAULT_MIN_SCORE,
                    help=f"quality pass bar (default {ws_judge.DEFAULT_MIN_SCORE})")
    args = ap.parse_args(argv)

    snap_path = Path(args.snapshot) if args.snapshot else _latest_snapshot()
    if not snap_path or not snap_path.exists():
        print("no snapshot found — run tests.e2e.ws_runner or ws_e2e first")
        return 2

    snap, run_id = _load_snapshot(snap_path)
    out = generate_from_snapshot(
        snap, run_id=run_id, run_judge=args.judge,
        write_baseline=args.write_baseline, min_score=args.min_score,
    )
    m = out["metrics"]
    q = out["quality"]
    print(f"\nGlimi Workspace report — backend={m['backend']} run_id={run_id}")
    print(f"  structural: {m['verdict']['status']}")
    if q.get("status") == "scored":
        print(f"  quality:    {q.get('overall')}/10 "
              f"({'pass' if q.get('pass') else 'fail'})")
    else:
        print(f"  quality:    {q.get('status')} ({q.get('reason', q.get('rationale', ''))})")
    print(f"  cost:       ${m['cost']['total_usd']:.4f} "
          f"({m['cost']['call_count']} calls)")
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
