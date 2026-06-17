"""Eval runner — run every golden case through the real Glimi runtime and score it.

For each agent-turn case the runner:
  1. builds a FRESH ``Glimi(backend=...)`` (runtime + memory module globals are
     process-singletons re-injected on each instantiation, so cases MUST run
     sequentially — one Glimi per case, no overlap),
  2. registers the case's agent (persona + agent_type),
  3. seeds any pinned/long-term memory,
  4. sends the input and captures the reply + the turn's parsed tool calls
     (``runtime.pop_tool_calls``),
  5. runs DETERMINISTIC checks (expected tool, permission boundary, memory
     grounding, no-hallucination), then
  6. optionally runs the reused LLM-as-judge for subjective quality.

Supervisor cases are judge-only: a transcript is fed to the reused supervisor
``JUDGE_PROMPT`` (see eval/judge.py) and the verdict is asserted.

Backend honesty:
  * ``echo`` is deterministic, always available, and NEVER emits ``<tools>``. So
    echo mode validates WIRING + deterministic checks and **skips the LLM judge**
    (marked ``SKIPPED``). No fabricated scores.
  * ``claude_cli`` / ``ollama`` produce real replies + can emit tool calls, so the
    judge runs (when the Claude CLI is present) for full scores.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import judge as _judge
from .schema import GoldenCase, load_cases

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


# ── deterministic check helpers ───────────────────────────────────────
def _tool_names(calls: list) -> list[str]:
    return [getattr(c, "name", None) for c in calls]


def _run_agent_case(case: GoldenCase, backend: str) -> dict[str, Any]:
    """Build a fresh Glimi, run the case, return raw observations + det. checks."""
    # Imported lazily so `python -m eval` works even if a heavy backend dep is
    # missing for an unrelated backend.
    from glimi import Glimi
    from glimi import memory as glimi_memory
    from glimi.tools import (
        ValidationError,
        check_permission,
        get_tool,
        validate_args,
    )

    setup = case.setup
    agent_id = setup.get("agent_id") or _slug(setup.get("name") or case.id)
    agent_type = setup.get("agent_type", "persona")
    model = setup.get("model")

    g = Glimi(backend=backend)
    g.add_agent(
        agent_id,
        name=setup.get("name"),
        persona=setup.get("persona", ""),
        agent_type=agent_type,
        model=model,
    )
    channel = f"dm-{agent_id}"

    # Seed memory (pinned facts etc.).
    for m in setup.get("seeded_memory", []) or []:
        g.store.add_memory(
            agent_id,
            channel,
            int(m.get("level", 3)),
            m.get("content", ""),
            is_pinned=bool(m.get("is_pinned", False)),
            importance=int(m.get("importance", 5)),
        )

    # Capture the memory context the runtime would inject this turn (grounding).
    mem_context = glimi_memory.get_memory_context(
        agent_id, channel, user_message=case.input
    )

    # Run the turn.
    out_lines = g.send(agent_id, case.input)
    output = "\n".join(out_lines)
    calls = g.runtime.pop_tool_calls(agent_id)
    call_names = _tool_names(calls)

    # ── deterministic checks ──
    det: list[dict] = []
    checks = case.checks or {}

    def record(name: str, ok: bool, detail: str = ""):
        det.append({"check": name, "pass": bool(ok), "detail": detail})

    out_lower = output.lower()

    # must_contain / must_not_contain (substring, case-insensitive)
    for needle in checks.get("must_contain", []) or []:
        record("must_contain", needle.lower() in out_lower, f"{needle!r}")
    for needle in checks.get("must_not_contain", []) or []:
        record("must_not_contain", needle.lower() not in out_lower, f"{needle!r}")

    # expect_no_tool — central anti-hallucination guard (echo-checkable)
    if checks.get("expect_no_tool"):
        record("expect_no_tool", len(calls) == 0,
               f"got tool calls: {call_names}" if calls else "no tool calls")

    # tool_forbidden — permission boundary: this tool must NEVER appear
    forbidden = checks.get("tool_forbidden")
    if forbidden:
        record("tool_forbidden", forbidden not in call_names,
               f"forbidden {forbidden!r} present" if forbidden in call_names else "absent")

    # expect_tool — the right tool was invoked (only meaningful when emitted).
    expected = checks.get("expect_tool")
    if expected:
        if backend == "echo":
            # Echo never emits <tools>; assert the deterministic no-hallucination
            # path instead of asserting a tool we know cannot appear.
            record("expect_tool[echo:no-hallucination]", len(calls) == 0,
                   "echo emits no tools; checked no hallucinated action")
        else:
            present = expected in call_names
            record("expect_tool", present,
                   f"expected {expected!r}, got {call_names}")
            if present and checks.get("tool_args_valid"):
                spec = get_tool(expected)
                call = next(c for c in calls if c.name == expected)
                try:
                    validate_args(spec, call.args)
                    record("tool_args_valid", True, "")
                except ValidationError as e:
                    record("tool_args_valid", False, str(e))
            if present and checks.get("tool_permission_ok"):
                spec = get_tool(expected)
                ok, reason = check_permission(spec, agent_type)
                record("tool_permission_ok", ok, reason)

    # grounded_fact — the seeded fact surfaces in the injected memory context
    # (deterministic, echo-checkable) and, on a real backend, in the reply.
    fact = checks.get("grounded_fact")
    if fact:
        in_ctx = fact.lower() in mem_context.lower()
        record("grounded_in_context", in_ctx,
               f"{fact!r} {'in' if in_ctx else 'NOT in'} memory context")
        if backend != "echo":
            record("grounded_in_response", fact.lower() in out_lower,
                   f"{fact!r} {'in' if fact.lower() in out_lower else 'NOT in'} reply")

    return {
        "output": output,
        "tool_calls": [
            {"name": getattr(c, "name", None), "args": getattr(c, "args", {})}
            for c in calls
        ],
        "memory_context_present": bool(mem_context.strip()),
        "deterministic": det,
        "det_pass": all(d["pass"] for d in det) if det else True,
    }


def _run_supervisor_case(case: GoldenCase, backend: str) -> dict[str, Any]:
    """Judge-only: feed the transcript to the reused supervisor judge + assert."""
    if backend == "echo" or not _judge.judge_available():
        return {
            "judge": "SKIPPED",
            "reason": "supervisor cases need the Claude CLI judge"
                      + (" (echo mode)" if backend == "echo" else " (claude not on PATH)"),
            "deterministic": [],
            "det_pass": True,  # nothing to check deterministically; not a failure
        }
    verdict = _judge.judge_transcript(case.transcript)
    det: list[dict] = []
    exp = case.expect or {}

    def record(name: str, ok: bool, detail: str = ""):
        det.append({"check": name, "pass": bool(ok), "detail": detail})

    if verdict["status"] != "scored":
        record("judge_ran", False, verdict.get("summary", "judge error"))
        return {"judge": "scored", "verdict": verdict, "deterministic": det, "det_pass": False}

    sev = verdict.get("severity")
    score = verdict.get("score")
    if "severity" in exp:
        record("severity", sev == exp["severity"], f"got {sev!r}, want {exp['severity']!r}")
    if "severity_not" in exp:
        record("severity_not", sev != exp["severity_not"], f"got {sev!r}, must not be {exp['severity_not']!r}")
    if "min_score" in exp and isinstance(score, (int, float)):
        record("min_score", score >= exp["min_score"], f"got {score}, min {exp['min_score']}")
    if "max_score" in exp and isinstance(score, (int, float)):
        record("max_score", score <= exp["max_score"], f"got {score}, max {exp['max_score']}")
    if "issue_categories_any" in exp:
        cats = {i.get("category") for i in (verdict.get("issues") or []) if isinstance(i, dict)}
        want = set(exp["issue_categories_any"])
        record("issue_categories_any", bool(cats & want), f"got {sorted(cats)}, want any of {sorted(want)}")

    return {
        "judge": "scored",
        "verdict": verdict,
        "deterministic": det,
        "det_pass": all(d["pass"] for d in det) if det else True,
    }


def _slug(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-") or "agent"


def run_case(case: GoldenCase, backend: str) -> dict[str, Any]:
    """Run one case end-to-end and return its result record."""
    base: dict[str, Any] = {
        "id": case.id,
        "capability": case.capability,
        "backend": backend,
        "source": case.source,
    }
    try:
        if case.supervisor_judge:
            obs = _run_supervisor_case(case, backend)
        else:
            obs = _run_agent_case(case, backend)
            # LLM judge for subjective quality (agent-turn cases only).
            obs["judge"] = "SKIPPED"
            if backend != "echo" and case.judge_rubric and _judge.judge_available():
                jr = _judge.judge_response(
                    capability=case.capability,
                    criteria=case.judge_rubric.get("criteria", ""),
                    user_input=case.input,
                    agent_output=obs.get("output", ""),
                    min_score=int(case.judge_rubric.get("min_score", 6)),
                )
                obs["judge"] = jr
    except Exception as e:  # a runtime explosion is itself a failure
        base.update({"error": f"{type(e).__name__}: {e}", "passed": False,
                     "det_pass": False, "judge": "ERROR"})
        return base

    base.update(obs)

    # A case PASSES when its deterministic checks pass AND, if the judge ran for
    # this case, the judge passed. Skipped/absent judge does not fail a case.
    det_pass = obs.get("det_pass", True)
    judge = obs.get("judge")
    judge_pass = True
    if isinstance(judge, dict):  # agent-turn judge result
        judge_pass = bool(judge.get("pass", False)) if judge.get("status") == "scored" else False
    base["judge_ran"] = isinstance(judge, dict) and judge.get("status") == "scored"
    base["passed"] = bool(det_pass and (judge_pass if base["judge_ran"] else True))
    return base


def aggregate(results: list[dict]) -> dict[str, Any]:
    """Per-capability + overall aggregates."""
    by_cap: dict[str, dict] = {}
    for r in results:
        cap = r["capability"]
        b = by_cap.setdefault(cap, {"total": 0, "passed": 0, "judged": 0, "judge_scores": []})
        b["total"] += 1
        b["passed"] += 1 if r.get("passed") else 0
        if r.get("judge_ran"):
            b["judged"] += 1
            j = r.get("judge")
            if isinstance(j, dict) and isinstance(j.get("score"), (int, float)):
                b["judge_scores"].append(j["score"])
    caps = {}
    for cap, b in by_cap.items():
        caps[cap] = {
            "total": b["total"],
            "passed": b["passed"],
            "pass_rate": round(b["passed"] / b["total"], 4) if b["total"] else 0.0,
            "judged": b["judged"],
            "avg_judge_score": (round(sum(b["judge_scores"]) / len(b["judge_scores"]), 2)
                                if b["judge_scores"] else None),
        }
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    return {
        "overall": {
            "total": total,
            "passed": passed,
            "pass_rate": round(passed / total, 4) if total else 0.0,
        },
        "per_capability": caps,
    }


def run(backend: str = "echo", golden_dir: Optional[Path] = None,
        out_path: Optional[Path] = None) -> dict[str, Any]:
    """Load + run + score all golden cases. Returns the full report dict."""
    cases = load_cases(golden_dir)
    judge_active = backend != "echo" and _judge.judge_available()
    results = [run_case(c, backend) for c in cases]  # sequential by contract
    agg = aggregate(results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "judge_mode": "scored" if judge_active else "SKIPPED",
        "judge_skipped_reason": (
            None if judge_active
            else ("echo backend (deterministic, no LLM cost)" if backend == "echo"
                  else "claude CLI not on PATH")
        ),
        "case_count": len(cases),
        "results": results,
        "aggregates": agg,
        # The harness "passes" when every deterministic check passes. Judge
        # scores feed the regression gate, not the structural pass/fail, so an
        # echo CI run is a clean structure guard.
        "pass": all(r.get("passed") for r in results),
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _print_summary(report: dict) -> None:
    agg = report["aggregates"]
    print(f"\nGlimi eval — backend={report['backend']} judge={report['judge_mode']}")
    if report.get("judge_skipped_reason"):
        print(f"  judge skipped: {report['judge_skipped_reason']}")
    print(f"  cases: {report['case_count']}  "
          f"overall pass: {agg['overall']['passed']}/{agg['overall']['total']} "
          f"({agg['overall']['pass_rate']*100:.0f}%)")
    for cap, b in sorted(agg["per_capability"].items()):
        line = (f"  - {cap:<11} {b['passed']}/{b['total']} pass")
        if b["avg_judge_score"] is not None:
            line += f"  avg-judge {b['avg_judge_score']}"
        elif b["judged"] == 0:
            line += "  (judge skipped)"
        print(line)
    for r in report["results"]:
        if not r.get("passed"):
            fails = [d for d in r.get("deterministic", []) if not d["pass"]]
            detail = "; ".join(f"{d['check']}: {d['detail']}" for d in fails) or r.get("error", "")
            print(f"  FAIL {r['id']}: {detail}")
    print(f"\n  RESULT: {'PASS' if report['pass'] else 'FAIL'}\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="eval run", description="Run the Glimi golden-set eval.")
    ap.add_argument("--backend", default="echo",
                    help="LLM backend: echo (default, no cost) | claude_cli | ollama")
    ap.add_argument("--golden-dir", default=None, help="override golden case dir")
    ap.add_argument("--out", default=None,
                    help="report JSON path (default eval/reports/latest-<backend>.json)")
    ap.add_argument("--quiet", action="store_true", help="suppress human summary")
    args = ap.parse_args(argv)

    out = Path(args.out) if args.out else REPORTS_DIR / f"latest-{args.backend}.json"
    golden = Path(args.golden_dir) if args.golden_dir else None
    report = run(backend=args.backend, golden_dir=golden, out_path=out)
    if not args.quiet:
        _print_summary(report)
        print(f"  report: {out}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
