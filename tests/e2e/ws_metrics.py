# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Workspace consolidated metrics — ONE schema for the portfolio layer.

``ws_verdict`` produces a PASS/WARN/FAIL verdict with structural metrics (rounds,
delegation, A2A, meta leaks, deliverable lengths). The dashboard exposes
cost/latency/by_agent via ``/w/{id}/api/usage`` (``DashboardReader.usage``). The
deliverable judge (``ws_judge``) scores the final document. Three separate views.

This module folds all three into a SINGLE metrics object — the thing a report and
a regression gate both consume — so there is exactly one shape to reason about::

    {
      "run_id", "backend", "goal", "generated_at",
      "verdict":  {status, verdict_line, issues: [...]},   # from ws_verdict
      "structure": {rounds, delegation, a2a, deliverables, meta_leaks, ...},
      "cost":     {total_usd, call_count, input_tokens, output_tokens, estimated},
      "latency":  {avg_ms, seconds_wall},
      "by_agent": [ {agent_id, total_cost, call_count, ...}, ... ],
      "quality":  {status, overall, scores:{axis:..}, pass, rationale, min_score},
      "pass_criteria": {structural_ok, quality_ok, overall_ok}
    }

It reuses ``ws_verdict.judge_snapshot`` (no re-implementation) for the structural
half, and accepts a quality verdict from ``ws_judge`` for the quality half. Usage
is read from the snapshot the runner already captured (in-memory ``usage`` rows,
or the served ``usage_aggregate`` when rows aren't reachable over HTTP).

Also here: a committable BASELINE (``ws-baseline.json``) + run-over-run COMPARISON,
following the ``glimi-core/eval/regression.py`` pattern (backend-tagged, tolerance-
based, exits non-zero on regression).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from tests.e2e import ws_judge, ws_verdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"
BASELINE_PATH = PROJECT_ROOT / "tests" / "e2e" / "ws-baseline.json"


# ── cost / latency / by-agent, from the snapshot the runner captured ─────────────

def _usage_view(snap: dict) -> tuple[dict, dict, list]:
    """Distill cost + latency + by_agent from the snapshot.

    Two sources, in priority order:
      1. ``usage_aggregate`` — the served ``/api/usage`` dict (ws_e2e path). It
         already carries spend_month / call_count_month / avg_latency_ms / by_agent.
      2. ``usage`` rows — the in-memory ledger (headless ws_runner path). We
         aggregate them with the SAME math the store's ``usage_spend`` /
         ``usage_by_agent`` use, so both paths produce identical shapes.

    On echo both are empty (echo logs no spend) → all-zero cost, which is correct
    and honest ($0 self-test).
    """
    agg = snap.get("usage_aggregate") or {}
    rows = snap.get("usage") or []

    if agg:
        cost = {
            "total_usd": round(float(agg.get("spend_month", 0.0) or 0.0), 6),
            "call_count": int(agg.get("call_count_month", 0) or 0),
            "input_tokens": int(agg.get("input_tokens_month", 0) or 0),
            "output_tokens": int(agg.get("output_tokens_month", 0) or 0),
            "estimated_count": int(agg.get("estimated_count_month", 0) or 0),
            "source": "served_usage_api",
        }
        latency = {"avg_ms": int(agg.get("avg_latency_ms", 0) or 0)}
        by_agent = list(agg.get("by_agent") or [])
        return cost, latency, by_agent

    # Aggregate the raw in-memory rows (mirror store.usage_spend / usage_by_agent).
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    cost = {
        "total_usd": round(float(sum(r.get("est_cost", 0) or 0 for r in rows)), 6),
        "call_count": len(rows),
        "input_tokens": int(sum(int(r.get("input_tokens", 0) or 0) for r in rows)),
        "output_tokens": int(sum(int(r.get("output_tokens", 0) or 0) for r in rows)),
        "estimated_count": int(sum(int(r.get("estimated", 0) or 0) for r in rows)),
        "source": "inmemory_usage_rows" if rows else "none",
    }
    latency = {"avg_ms": int(sum(lat) / len(lat)) if lat else 0}

    groups: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("agent_id"), r.get("model"), r.get("backend"))
        g = groups.setdefault(key, {
            "agent_id": r.get("agent_id"), "model": r.get("model"),
            "backend": r.get("backend"), "total_cost": 0.0, "call_count": 0,
            "input_tokens": 0, "output_tokens": 0,
        })
        g["total_cost"] += float(r.get("est_cost", 0) or 0)
        g["call_count"] += 1
        g["input_tokens"] += int(r.get("input_tokens", 0) or 0)
        g["output_tokens"] += int(r.get("output_tokens", 0) or 0)
    by_agent = sorted(groups.values(),
                      key=lambda x: (x["total_cost"], x["call_count"]), reverse=True)
    return cost, latency, by_agent


def _structure_view(verdict: dict) -> dict:
    """Pull the structural numbers a reader/regression cares about out of the
    verdict's full metrics blob (which carries everything ws_verdict computed)."""
    m = verdict.get("metrics", {}) or {}
    deleg = m.get("delegation_by_channel", {}) or {}
    a2a = m.get("a2a_by_channel", {}) or {}
    # A2A "both spoke" count: how many A2A channels had >0 from both sides.
    a2a_both = 0
    for _ch, sides in a2a.items():
        vals = [v for v in sides.values() if isinstance(v, int)]
        if vals and all(v > 0 for v in vals):
            a2a_both += 1
    return {
        "rounds_run": m.get("rounds_run", verdict.get("rounds")),
        "stopped_reason": m.get("stopped_reason", verdict.get("stopped_reason")),
        "deliverables_count": m.get("deliverables_count", 0),
        "deliverable_len_first": m.get("deliverable_len_first"),
        "deliverable_len_last": m.get("deliverable_len_last"),
        "goal_advanced": m.get("goal_advanced"),
        "delegation_by_channel": deleg,
        "delegation_channels_hit": sum(1 for v in deleg.values() if v),
        "a2a_by_channel": a2a,
        "a2a_channels_both_spoke": a2a_both,
        "owner_instructions_distinct": m.get("owner_instructions_distinct"),
        "meta_leaks": m.get("meta_leaks", 0),
        "error_leaks": m.get("error_leaks", 0),
        "usage_total_cost": m.get("usage_total_cost"),
    }


# ── the consolidated metrics object ──────────────────────────────────────────────

def build_metrics(snap: dict, *, run_id: str, quality: Optional[dict] = None) -> dict:
    """Consolidate structure + cost + latency + by_agent + quality → one object.

    ``snap`` is the runner's snapshot (headless ``ws-store-*.json`` or the web
    ``ws-e2e-store-*.json``). ``quality`` is a ``ws_judge`` verdict (or None →
    treated as skipped). Reuses ``ws_verdict.judge_snapshot`` for the structural
    verdict so there is exactly one structural-criteria implementation.
    """
    verdict = ws_verdict.judge_snapshot(snap, run_id=run_id)
    structure = _structure_view(verdict)
    cost, latency, by_agent = _usage_view(snap)
    latency["seconds_wall"] = snap.get("elapsed_seconds")

    q = quality or {"status": "skipped", "overall": None, "pass": None,
                    "scores": {}, "rationale": "no quality verdict supplied",
                    "min_score": ws_judge.DEFAULT_MIN_SCORE}

    # Pass criteria: structural (verdict not FAIL) AND, IF quality was scored, it
    # passed. A skipped quality (echo) does NOT fail the run — same honesty rule as
    # eval/runner.py (skipped judge ≠ failure).
    structural_ok = verdict.get("status") in ("PASS", "WARN")
    if q.get("status") == "scored":
        quality_ok = bool(q.get("pass"))
        quality_judged = True
    else:
        quality_ok = None
        quality_judged = False
    overall_ok = structural_ok and (quality_ok is not False)

    return {
        "run_id": run_id,
        "backend": snap.get("backend"),
        "goal": snap.get("goal"),
        "context": snap.get("context", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": {
            "status": verdict.get("status"),
            "verdict_line": verdict.get("verdict"),
            "issues": verdict.get("issues", []),
        },
        "structure": structure,
        "cost": cost,
        "latency": latency,
        "by_agent": by_agent,
        "quality": {
            "status": q.get("status"),
            "overall": q.get("overall"),
            "scores": q.get("scores", {}),
            "pass": q.get("pass"),
            "rationale": q.get("rationale", ""),
            "min_score": q.get("min_score"),
            "model": q.get("model"),
        },
        "pass_criteria": {
            "structural_ok": structural_ok,
            "quality_judged": quality_judged,
            "quality_ok": quality_ok,
            "overall_ok": overall_ok,
        },
    }


# ── baseline + run-over-run regression (eval/regression.py pattern) ──────────────

def distill_baseline(metrics: dict) -> dict:
    """Distill a metrics object into a compact, committable baseline.

    Backend-tagged (an echo baseline guards structure/wiring; a claude_cli baseline
    guards scored quality + cost), exactly like eval/regression.py's baseline.
    """
    s = metrics["structure"]
    return {
        "backend": metrics["backend"],
        "generated_at": metrics["generated_at"],
        "goal": metrics["goal"],
        "verdict_status": metrics["verdict"]["status"],
        "structure": {
            "rounds_run": s.get("rounds_run"),
            "deliverables_count": s.get("deliverables_count"),
            "delegation_channels_hit": s.get("delegation_channels_hit"),
            "a2a_channels_both_spoke": s.get("a2a_channels_both_spoke"),
            "meta_leaks": s.get("meta_leaks"),
            "error_leaks": s.get("error_leaks"),
            "deliverable_len_last": s.get("deliverable_len_last"),
        },
        "quality": {
            "status": metrics["quality"]["status"],
            "overall": metrics["quality"]["overall"],
        },
        "cost": {
            "total_usd": metrics["cost"]["total_usd"],
            "call_count": metrics["cost"]["call_count"],
        },
    }


def compare_to_baseline(metrics: dict, baseline: dict, *,
                        quality_threshold: float = 1.0,
                        len_threshold_frac: float = 0.5,
                        cost_threshold_frac: float = 0.5) -> dict:
    """Compare a metrics object to a baseline → trend verdict.

    Regressions (hard) — exit non-zero:
      * backend mismatch (refuse — echo-vs-scored comparison is meaningless),
      * verdict went FAIL when the baseline was PASS/WARN,
      * a structural floor dropped: fewer delegation channels hit, fewer A2A
        channels with both sides, NEW meta/error leaks,
      * a previously-scored quality.overall dropped by > ``quality_threshold``.

    Soft notes (informational, NOT a regression): deliverable length shrank a lot,
    cost grew a lot — surfaced as trend lines so a reader sees movement.
    """
    regressions: list[str] = []
    notes: list[str] = []

    if metrics["backend"] != baseline.get("backend"):
        return {"ok": False, "is_regression": True,
                "regressions": [f"backend mismatch: run={metrics['backend']} "
                                f"baseline={baseline.get('backend')} "
                                "(compare against a same-backend baseline)"],
                "notes": []}

    bs = baseline.get("structure", {}) or {}
    cs = metrics["structure"]

    # verdict status floor
    base_status = baseline.get("verdict_status")
    cur_status = metrics["verdict"]["status"]
    if base_status in ("PASS", "WARN") and cur_status == "FAIL":
        regressions.append(f"verdict FAIL (baseline {base_status})")
    else:
        notes.append(f"verdict {cur_status} (baseline {base_status})")

    # structural floors — never go down
    for key, label in (("delegation_channels_hit", "delegation channels"),
                       ("a2a_channels_both_spoke", "A2A both-spoke channels"),
                       ("deliverables_count", "deliverables")):
        b, c = bs.get(key), cs.get(key)
        if isinstance(b, int) and isinstance(c, int):
            if c < b:
                regressions.append(f"{label}: {c} < baseline {b}")
            else:
                notes.append(f"{label}: {c} (baseline {b})")

    # leaks — any NEW leak vs a clean baseline is a regression
    for key, label in (("meta_leaks", "meta leaks"), ("error_leaks", "error leaks")):
        b, c = bs.get(key, 0) or 0, cs.get(key, 0) or 0
        if c > b:
            regressions.append(f"{label}: {c} > baseline {b}")

    # quality score (only when BOTH sides scored)
    bq = (baseline.get("quality") or {}).get("overall")
    cq = metrics["quality"].get("overall")
    if isinstance(bq, (int, float)) and isinstance(cq, (int, float)):
        if cq < bq - quality_threshold:
            regressions.append(f"quality.overall {cq:.1f} < baseline {bq:.1f} "
                               f"(thr {quality_threshold})")
        else:
            notes.append(f"quality.overall {cq:.1f} (baseline {bq:.1f})")
    elif metrics["quality"].get("status") == "skipped":
        notes.append("quality: skipped (judge not run)")

    # soft trend: deliverable length
    bl, cl = bs.get("deliverable_len_last"), cs.get("deliverable_len_last")
    if isinstance(bl, int) and bl > 0 and isinstance(cl, int):
        if cl < bl * len_threshold_frac:
            notes.append(f"⚠ deliverable shrank: {cl} chars < {len_threshold_frac:.0%} "
                         f"of baseline {bl} (soft)")
        else:
            notes.append(f"deliverable length: {cl} chars (baseline {bl})")

    # soft trend: cost
    bc = (baseline.get("cost") or {}).get("total_usd")
    cc = metrics["cost"].get("total_usd")
    if isinstance(bc, (int, float)) and isinstance(cc, (int, float)):
        if bc > 0 and cc > bc * (1 + cost_threshold_frac):
            notes.append(f"⚠ cost grew: ${cc:.4f} > baseline ${bc:.4f} "
                         f"+{cost_threshold_frac:.0%} (soft)")
        else:
            notes.append(f"cost: ${cc:.4f} (baseline ${bc:.4f})")

    return {"ok": not regressions, "is_regression": bool(regressions),
            "regressions": regressions, "notes": notes,
            "baseline_backend": baseline.get("backend"),
            "baseline_generated_at": baseline.get("generated_at")}


def load_baseline(path: Optional[Path] = None) -> Optional[dict]:
    p = Path(path) if path else BASELINE_PATH
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write_baseline(metrics: dict, path: Optional[Path] = None) -> Path:
    p = Path(path) if path else BASELINE_PATH
    bl = distill_baseline(metrics)
    p.write_text(json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
