"""Unit tests for the eval/ evaluation harness — no LLM, no API key.

Covers:
  - golden set loads + schema-validates (every shipped case),
  - schema rejects malformed cases,
  - runner deterministic checks (echo end-to-end: persona/tool/memory/fallback),
  - supervisor cases honestly skip the judge in echo mode,
  - regression gate logic (pass within threshold, fail on a drop, backend mismatch),
  - production feedback loop (a flagged turn → a valid golden case).

Run:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_eval_harness.py -q
"""
from __future__ import annotations

import json

import pytest

from eval import load_cases
from eval.schema import CAPABILITIES, GoldenCase, SchemaError, _validate
from eval.runner import aggregate, run, run_case
from eval.regression import baseline_from_report, compare
from eval.from_production import turn_to_case


# ── golden set: loads + validates ─────────────────────────────────────
def test_golden_set_loads_and_validates():
    cases = load_cases()
    assert len(cases) >= 12, "golden set should have ~12-16 curated cases"
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    covered = {c.capability for c in cases}
    assert covered == CAPABILITIES, f"every capability must be covered, missing {CAPABILITIES - covered}"
    for c in cases:
        assert isinstance(c, GoldenCase)
        assert c.capability in CAPABILITIES


def test_schema_rejects_bad_capability():
    with pytest.raises(SchemaError):
        _validate({"id": "x", "capability": "nonsense", "input": "hi",
                   "setup": {"persona": "p"}}, "t")


def test_schema_rejects_missing_persona():
    with pytest.raises(SchemaError):
        _validate({"id": "x", "capability": "persona", "input": "hi", "setup": {}}, "t")


def test_schema_rejects_supervisor_without_transcript():
    with pytest.raises(SchemaError):
        _validate({"id": "x", "capability": "supervisor",
                   "expect": {"severity": "ok"}}, "t")


def test_schema_rejects_empty_input():
    with pytest.raises(SchemaError):
        _validate({"id": "x", "capability": "fallback", "input": "   ",
                   "setup": {"persona": "p"}}, "t")


# ── runner: deterministic checks via the real runtime (echo) ──────────
def test_runner_memory_grounding_check_echo():
    case = GoldenCase(
        id="t-mem", capability="memory",
        setup={"persona": "Nova — remembers.", "agent_type": "persona", "name": "Nova",
               "seeded_memory": [{"level": 3, "content": "Owner is allergic to peanuts.",
                                  "is_pinned": True, "importance": 9}]},
        input="dinner ideas?",
        checks={"grounded_fact": "peanut"},
    )
    res = run_case(case, backend="echo")
    assert res["passed"] is True
    det = {d["check"]: d["pass"] for d in res["deterministic"]}
    assert det["grounded_in_context"] is True


def test_runner_grounding_fails_when_fact_absent():
    case = GoldenCase(
        id="t-mem-miss", capability="memory",
        setup={"persona": "Nova", "agent_type": "persona", "name": "Nova"},  # no seeded mem
        input="dinner ideas?",
        checks={"grounded_fact": "peanut"},
    )
    res = run_case(case, backend="echo")
    assert res["passed"] is False  # fact not in context → fails


def test_runner_expect_no_tool_and_permission_boundary_echo():
    case = GoldenCase(
        id="t-tool", capability="tool_use",
        setup={"persona": "Nova — ordinary.", "agent_type": "persona", "name": "Nova"},
        input="create a new room please",
        checks={"expect_no_tool": True, "tool_forbidden": "create_room"},
    )
    res = run_case(case, backend="echo")
    assert res["passed"] is True
    assert res["tool_calls"] == []  # echo never hallucinates a tool


def test_runner_must_not_contain_echo():
    case = GoldenCase(
        id="t-persona", capability="persona",
        setup={"persona": "Nova.", "agent_type": "persona", "name": "Nova"},
        input="hi there",
        checks={"must_not_contain": ["as an ai", "language model"]},
    )
    res = run_case(case, backend="echo")
    assert res["passed"] is True


def test_runner_supervisor_skips_judge_in_echo():
    case = GoldenCase(
        id="t-sup", capability="supervisor", supervisor_judge=True,
        transcript=[{"channel": "c", "speaker": "Nova", "message": "As an AI I must clarify..."}],
        expect={"severity_not": "ok", "max_score": 4},
    )
    res = run_case(case, backend="echo")
    # Echo cannot run the Claude-CLI judge → honestly skipped, not a failure.
    assert res["judge"] == "SKIPPED"
    assert res["passed"] is True


# ── runner: end-to-end echo run + report shape ────────────────────────
def test_echo_run_end_to_end():
    report = run(backend="echo")
    assert report["backend"] == "echo"
    assert report["judge_mode"] == "SKIPPED"
    assert report["case_count"] >= 12
    assert report["pass"] is True  # the shipped golden set must be green under echo
    agg = report["aggregates"]
    assert agg["overall"]["pass_rate"] == 1.0
    assert set(agg["per_capability"]) == CAPABILITIES
    # no fabricated judge scores in echo mode
    for cap in agg["per_capability"].values():
        assert cap["avg_judge_score"] is None


# ── regression gate logic ─────────────────────────────────────────────
def _fake_report(backend="echo", overall_rate=1.0, mem_rate=1.0, mem_judge=None):
    return {
        "backend": backend, "judge_mode": "SKIPPED",
        "generated_at": "now", "case_count": 3,
        "aggregates": {
            "overall": {"total": 3, "passed": int(3 * overall_rate), "pass_rate": overall_rate},
            "per_capability": {
                "memory": {"total": 3, "passed": int(3 * mem_rate), "pass_rate": mem_rate,
                           "judged": 0, "avg_judge_score": mem_judge},
            },
        },
    }


def test_gate_passes_when_equal():
    rep = _fake_report()
    bl = baseline_from_report(rep)
    v = compare(rep, bl, threshold=0.0)
    assert v["ok"] is True


def test_gate_fails_on_pass_rate_drop():
    base = baseline_from_report(_fake_report(overall_rate=1.0, mem_rate=1.0))
    dropped = _fake_report(overall_rate=0.66, mem_rate=0.33)
    v = compare(dropped, base, threshold=0.0)
    assert v["ok"] is False
    assert any("pass_rate" in r for r in v["regressions"])


def test_gate_passes_within_threshold():
    base = baseline_from_report(_fake_report(overall_rate=1.0, mem_rate=1.0))
    dropped = _fake_report(overall_rate=0.66, mem_rate=0.66)
    v = compare(dropped, base, threshold=0.5)  # generous tolerance
    assert v["ok"] is True


def test_gate_fails_on_backend_mismatch():
    base = baseline_from_report(_fake_report(backend="echo"))
    run_rep = _fake_report(backend="claude_cli")
    v = compare(run_rep, base)
    assert v["ok"] is False
    assert any("backend mismatch" in r for r in v["regressions"])


def test_gate_fails_on_judge_score_drop():
    base = baseline_from_report(_fake_report(mem_judge=8.0))
    dropped = _fake_report(mem_judge=5.0)
    v = compare(dropped, base, threshold=0.0, judge_threshold=1.0)
    assert v["ok"] is False
    assert any("avg_judge_score" in r for r in v["regressions"])


# ── production feedback loop ───────────────────────────────────────────
def test_production_turn_promotes_to_valid_persona_case():
    turn = {
        "speaker": "Nova", "agent_type": "persona", "persona": "Nova — warm.",
        "input": "are you real?",
        "bad_output": "Yes, as an AI language model I am artificial.",
        "leak": "as an AI language model",
    }
    case = turn_to_case(turn, idx=0)
    assert case["capability"] == "persona"
    assert "as an AI language model" in case["checks"]["must_not_contain"]
    # the generated case must itself pass schema validation
    _validate(case, source="test")


def test_production_turn_infers_memory_and_grounds():
    turn = {
        "speaker": "Mina", "agent_type": "persona", "persona": "Mina.",
        "input": "dinner?", "bad_output": "what are you allergic to?",
        "capability": "memory",
        "seeded_memory": [{"level": 3, "content": "Owner is allergic to peanuts.",
                           "is_pinned": True, "importance": 9}],
        "grounded_fact": "peanut",
    }
    case = turn_to_case(turn, idx=1)
    assert case["capability"] == "memory"
    assert case["checks"]["grounded_fact"] == "peanut"
    _validate(case, source="test")


def test_promoted_memory_case_runs_through_runner():
    """A promoted case must be runnable end-to-end (closes the loop)."""
    turn = {
        "speaker": "Mina", "agent_type": "persona", "persona": "Mina.",
        "input": "dinner?", "bad_output": "what are you allergic to?",
        "seeded_memory": [{"level": 3, "content": "Owner is allergic to peanuts.",
                           "is_pinned": True, "importance": 9}],
        "grounded_fact": "peanut",
    }
    case_dict = turn_to_case(turn, idx=2)
    case = _validate(case_dict, source="test")
    res = run_case(case, backend="echo")
    assert "passed" in res
