"""Regression gate — compare a run's aggregates to a stored baseline.

A *baseline* (``eval/baseline.json``) records the known-good aggregates from a
prior scored run. The gate reruns the eval (or reads a report), compares it to
the baseline within a tolerance, and exits non-zero if anything regressed:

  * overall pass-rate dropped by more than ``--threshold`` (default 0.0 — no
    structural regression allowed),
  * any per-capability pass-rate dropped by more than ``--threshold``,
  * a previously-judged capability's average judge score dropped by more than
    ``--judge-threshold`` (default 1.0 point).

The baseline is backend-tagged. An ``echo`` baseline guards structure/wiring;
a ``claude_cli`` baseline guards scored quality. Gate against a baseline whose
backend matches the run, or the gate refuses (mixing echo + scored is meaningless).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from .runner import REPORTS_DIR, run

BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"


def baseline_from_report(report: dict) -> dict[str, Any]:
    """Distill a report into a compact, committable baseline."""
    agg = report["aggregates"]
    return {
        "backend": report["backend"],
        "judge_mode": report["judge_mode"],
        "generated_at": report["generated_at"],
        "case_count": report["case_count"],
        "overall": agg["overall"],
        "per_capability": agg["per_capability"],
    }


def compare(report: dict, baseline: dict, *, threshold: float = 0.0,
            judge_threshold: float = 1.0) -> dict[str, Any]:
    """Compare a report's aggregates to a baseline. Returns a verdict dict."""
    regressions: list[str] = []
    notes: list[str] = []

    if report["backend"] != baseline.get("backend"):
        regressions.append(
            f"backend mismatch: run={report['backend']} baseline={baseline.get('backend')} "
            "(gate a run against a same-backend baseline)"
        )
        return {"ok": False, "regressions": regressions, "notes": notes}

    agg = report["aggregates"]

    # overall pass-rate
    cur = agg["overall"]["pass_rate"]
    base = baseline["overall"]["pass_rate"]
    if cur < base - threshold:
        regressions.append(f"overall pass_rate {cur:.3f} < baseline {base:.3f} (thr {threshold})")
    else:
        notes.append(f"overall pass_rate {cur:.3f} (baseline {base:.3f})")

    # per-capability pass-rate + judge score
    for cap, b in baseline.get("per_capability", {}).items():
        c = agg["per_capability"].get(cap)
        if c is None:
            regressions.append(f"capability '{cap}' missing from run (baseline had {b['total']} cases)")
            continue
        if c["pass_rate"] < b["pass_rate"] - threshold:
            regressions.append(
                f"{cap}: pass_rate {c['pass_rate']:.3f} < baseline {b['pass_rate']:.3f} (thr {threshold})"
            )
        # judge score regression (only if both sides have a scored average)
        bj, cj = b.get("avg_judge_score"), c.get("avg_judge_score")
        if isinstance(bj, (int, float)) and isinstance(cj, (int, float)):
            if cj < bj - judge_threshold:
                regressions.append(
                    f"{cap}: avg_judge_score {cj:.2f} < baseline {bj:.2f} (thr {judge_threshold})"
                )

    return {"ok": not regressions, "regressions": regressions, "notes": notes}


def gate(backend: str = "echo", *, baseline_path: Optional[Path] = None,
         report_path: Optional[Path] = None, threshold: float = 0.0,
         judge_threshold: float = 1.0) -> dict[str, Any]:
    """Run (or load) an eval and compare it to the baseline. Returns the verdict."""
    bp = Path(baseline_path) if baseline_path else BASELINE_PATH
    if not bp.exists():
        return {"ok": False, "regressions": [f"no baseline at {bp} — write one with `eval baseline`"],
                "notes": []}
    baseline = json.loads(bp.read_text(encoding="utf-8"))

    if report_path and Path(report_path).exists():
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    else:
        report = run(backend=backend)

    verdict = compare(report, baseline, threshold=threshold, judge_threshold=judge_threshold)
    verdict["backend"] = backend
    verdict["report"] = report
    return verdict


def write_baseline(backend: str = "echo", out_path: Optional[Path] = None) -> Path:
    """Run an eval and freeze its aggregates as the new baseline."""
    report = run(backend=backend)
    bl = baseline_from_report(report)
    p = Path(out_path) if out_path else BASELINE_PATH
    p.write_text(json.dumps(bl, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="eval gate", description="Regression gate vs baseline.")
    ap.add_argument("--backend", default="echo", help="backend to run (default echo)")
    ap.add_argument("--baseline", default=None, help="baseline JSON path")
    ap.add_argument("--report", default=None,
                    help="compare an existing report JSON instead of re-running")
    ap.add_argument("--threshold", type=float, default=0.0,
                    help="allowed pass-rate drop (default 0.0 = none)")
    ap.add_argument("--judge-threshold", type=float, default=1.0,
                    help="allowed avg-judge-score drop (default 1.0)")
    args = ap.parse_args(argv)

    verdict = gate(
        backend=args.backend,
        baseline_path=Path(args.baseline) if args.baseline else None,
        report_path=Path(args.report) if args.report else None,
        threshold=args.threshold,
        judge_threshold=args.judge_threshold,
    )
    print(f"\nGlimi regression gate — backend={args.backend}")
    for n in verdict.get("notes", []):
        print(f"  ok: {n}")
    for r in verdict.get("regressions", []):
        print(f"  REGRESSION: {r}")
    print(f"\n  GATE: {'PASS' if verdict['ok'] else 'FAIL'}\n")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
