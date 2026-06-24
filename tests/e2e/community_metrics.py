# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Community consolidated metrics — ONE schema for the portfolio layer.

The Community analogue of :mod:`tests.e2e.ws_metrics`. It folds three views into a
single metrics object a report and a regression gate both consume:

  - **structure** — the Community structural facts (driven DMs, friend replies per
    DM, meta/error leaks), pulled from :func:`community_verdict.judge_snapshot`'s
    metrics blob (NOT re-implemented);
  - **cost / latency / by_agent** — read from the snapshot the runner captured,
    REUSING :func:`tests.e2e.ws_metrics._usage_view` verbatim (the served
    ``/api/usage`` shape — spend_month / call_count_month / avg_latency_ms /
    by_agent — is identical across Workspace and Community);
  - **quality** — a :mod:`community_judge` verdict (or skipped on echo).

It also reuses ws_metrics' baseline + run-over-run comparison machinery (the
eval/regression.py pattern), pointed at a Community-specific baseline file, so the
two tools share one comparison implementation.

Schema (mirrors ws_metrics)::

    {run_id, backend, goal, context, generated_at,
     verdict:{status, verdict_line, issues},
     structure:{driven_dms, friend_replies_by_dm, friend_replies_total, ...},
     cost:{total_usd, call_count, ...}, latency:{avg_ms, seconds_wall},
     by_agent:[...], quality:{status, overall, scores, pass, rationale, ...},
     pass_criteria:{structural_ok, quality_judged, quality_ok, overall_ok}}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tests.e2e import community_verdict
# Reuse the app-agnostic usage distillation + baseline/compare machinery from
# ws_metrics (the served usage shape + the regression algorithm are identical).
from tests.e2e.ws_metrics import _usage_view
from tests.e2e import community_judge

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"
BASELINE_PATH = PROJECT_ROOT / "tests" / "e2e" / "community-baseline.json"


def _structure_view(verdict: dict) -> dict:
    """Pull the Community structural numbers a reader/regression cares about out of
    the verdict's metrics blob."""
    m = verdict.get("metrics", {}) or {}
    replies = m.get("friend_replies_by_dm", {}) or {}
    return {
        "driven_dms": m.get("driven_dms", []),
        "driven_dm_count": len(m.get("driven_dms", []) or []),
        "friend_replies_by_dm": replies,
        "friend_replies_total": m.get("friend_replies_total", 0),
        "dms_with_reply": sum(1 for n in replies.values() if n),
        "owner_msgs_by_dm": m.get("owner_msgs_by_dm", {}),
        "meta_leaks": m.get("meta_leaks", 0),
        "error_leaks": m.get("error_leaks", 0),
    }


def build_metrics(snap: dict, *, run_id: str, quality: Optional[dict] = None) -> dict:
    """Consolidate structure + cost + latency + by_agent + quality → one object.

    Reuses ``community_verdict.judge_snapshot`` for the structural verdict (one
    structural-criteria implementation) and ``ws_metrics._usage_view`` for cost.
    ``quality`` is a ``community_judge`` verdict (or None → skipped). On echo both
    cost and quality are honest zeros/skips ($0 self-test)."""
    verdict = community_verdict.judge_snapshot(snap, run_id=run_id)
    structure = _structure_view(verdict)
    cost, latency, by_agent = _usage_view(snap)
    latency["seconds_wall"] = snap.get("elapsed_seconds")

    q = quality or {"status": "skipped", "overall": None, "pass": None,
                    "scores": {}, "rationale": "no quality verdict supplied",
                    "min_score": community_judge.DEFAULT_MIN_SCORE}

    # Pass criteria: structural not FAIL AND (if quality was scored) it passed. A
    # skipped quality (echo) does NOT fail the run (same honesty rule as ws).
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
    """Distill a metrics object into a compact, committable, backend-tagged baseline."""
    s = metrics["structure"]
    return {
        "backend": metrics["backend"],
        "generated_at": metrics["generated_at"],
        "goal": metrics["goal"],
        "verdict_status": metrics["verdict"]["status"],
        "structure": {
            "driven_dm_count": s.get("driven_dm_count"),
            "dms_with_reply": s.get("dms_with_reply"),
            "friend_replies_total": s.get("friend_replies_total"),
            "meta_leaks": s.get("meta_leaks"),
            "error_leaks": s.get("error_leaks"),
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
                        cost_threshold_frac: float = 0.5) -> dict:
    """Compare a metrics object to a baseline → trend verdict.

    Regressions (hard, exit non-zero): backend mismatch, verdict FAIL when baseline
    was PASS/WARN, a structural floor dropped (fewer DMs with a reply, fewer total
    replies), NEW meta/error leaks, or a previously-scored quality dropped past the
    threshold. Cost growth is a soft note."""
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

    base_status = baseline.get("verdict_status")
    cur_status = metrics["verdict"]["status"]
    if base_status in ("PASS", "WARN") and cur_status == "FAIL":
        regressions.append(f"verdict FAIL (baseline {base_status})")
    else:
        notes.append(f"verdict {cur_status} (baseline {base_status})")

    for key, label in (("dms_with_reply", "DMs with a friend reply"),
                       ("friend_replies_total", "total friend replies")):
        b, c = bs.get(key), cs.get(key)
        if isinstance(b, int) and isinstance(c, int):
            if c < b:
                regressions.append(f"{label}: {c} < baseline {b}")
            else:
                notes.append(f"{label}: {c} (baseline {b})")

    for key, label in (("meta_leaks", "meta leaks"), ("error_leaks", "error leaks")):
        b, c = bs.get(key, 0) or 0, cs.get(key, 0) or 0
        if c > b:
            regressions.append(f"{label}: {c} > baseline {b}")

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
    p.write_text(json.dumps(distill_baseline(metrics), ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p
