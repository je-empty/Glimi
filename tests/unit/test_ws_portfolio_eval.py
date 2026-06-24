# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Unit tests for the Workspace portfolio eval/metrics layer — no LLM, no network.

Covers (decision #6):
  - the deliverable-quality judge parses/normalizes a verdict + skips honestly,
  - consolidated metrics fold structure + cost/latency/by_agent + quality into ONE
    schema (echo snapshot → judge skipped, $0 cost),
  - baseline distill + run-over-run comparison (no-regression, regression on a
    structural drop / new leak / quality drop, backend-mismatch refusal),
  - the Markdown report renders the echo skeleton with 'judge: skipped (echo)' and
    a no-baseline note, and writes the .md + .json pair.

The LLM judge itself is never invoked (it spawns the claude CLI) — we test the
parsing/normalization by monkeypatching its single network primitive (call_haiku).

Run:
    PYTHONPATH=<repo>:<repo>/glimi-core:... python -m pytest tests/unit/test_ws_portfolio_eval.py -q
"""
from __future__ import annotations

import json

import pytest

from tests.e2e import ws_judge, ws_metrics, ws_report, ws_verdict


# ── a minimal echo-shaped snapshot the runner would dump ────────────────────────
def _echo_snapshot() -> dict:
    """A structurally-clean echo run snapshot (the shape ws_runner._snapshot_store
    + run() produce): 2 rounds, full delegation + A2A, no leaks, $0 usage."""
    coord = "coordinator"
    def msg(speaker, text):
        return {"id": 1, "speaker": speaker, "message": text, "timestamp": "2026-06-22T00:00:00+00:00"}
    return {
        "run_id": "ws-run-test",
        "backend": "echo",
        "goal": "테스트 목표",
        "context": "테스트 맥락",
        "owner_id": "owner",
        "elapsed_seconds": 1.2,
        "error": None,
        "rounds_requested": 2,
        "usage": [],
        "channels": {
            "dm-coordinator": [msg("owner", "지시 1"), msg(coord, "딜리버러블 1"),
                               msg("owner", "지시 2 다른 내용"), msg(coord, "딜리버러블 2")],
            "dm-researcher": [msg(coord, "리서치 부탁"), msg("researcher", "ok")],
            "dm-builder": [msg(coord, "빌드 부탁"), msg("builder", "ok")],
            "dm-critic": [msg(coord, "검토 부탁"), msg("critic", "ok")],
            "internal-researcher-critic": [msg("researcher", "a"), msg("critic", "b")],
            "internal-builder-researcher": [msg("builder", "a"), msg("researcher", "b")],
            "internal-owner": [msg("owner", "검토 메모 1"), msg("owner", "검토 메모 2")],
        },
        "drive_result": {
            "rounds": 2,
            "deliverables": ["딜리버러블 1 내용", "딜리버러블 2 더 긴 내용입니다"],
            "last_deliverable": "딜리버러블 2 더 긴 내용입니다",
            "done": False,
            "stopped_reason": "max_rounds",
        },
    }


# ── the judge: parse + skip honestly ────────────────────────────────────────────
def test_judge_skipped_returns_no_score():
    v = ws_judge.skipped("echo")
    assert v["status"] == "skipped"
    assert v["overall"] is None
    assert v["pass"] is None  # not True, not False — honestly absent
    assert v["scores"] == {}


def test_judge_empty_deliverable_is_error_not_fabricated():
    v = ws_judge.judge_deliverable(deliverable="   ", goal="g")
    assert v["status"] == "error"
    assert v["overall"] is None
    assert v["pass"] is False


def test_judge_parses_and_normalizes(monkeypatch):
    fake = json.dumps({
        "scores": {"completeness": 8, "structure": 9, "actionability": 7,
                   "specificity": 8, "correctness": 9},
        "overall": 8, "pass": True, "rationale": "구조 좋고 실행 가능."})
    monkeypatch.setattr(ws_judge, "call_haiku", lambda *a, **k: fake)
    v = ws_judge.judge_deliverable(deliverable="## 문서\n진짜 내용", goal="g",
                                   context="c", min_score=7)
    assert v["status"] == "scored"
    assert v["overall"] == 8
    assert v["pass"] is True
    assert set(v["scores"]) == set(ws_judge.RUBRIC_AXES)
    assert v["scores"]["structure"] == 9.0


def test_judge_derives_overall_and_pass_when_omitted(monkeypatch):
    # judge returned axis scores but no 'overall'/'pass' → derive mean + compare bar.
    fake = json.dumps({"scores": {"completeness": 4, "structure": 4,
                                  "actionability": 4, "specificity": 4,
                                  "correctness": 4}, "rationale": "약함"})
    monkeypatch.setattr(ws_judge, "call_haiku", lambda *a, **k: fake)
    v = ws_judge.judge_deliverable(deliverable="얕은 문서", goal="g", min_score=7)
    assert v["overall"] == 4.0
    assert v["pass"] is False  # 4 < 7


def test_judge_call_failure_is_error(monkeypatch):
    monkeypatch.setattr(ws_judge, "call_haiku", lambda *a, **k: "__ERROR__ boom")
    v = ws_judge.judge_deliverable(deliverable="x", goal="g")
    assert v["status"] == "error"
    assert v["pass"] is False


# ── consolidated metrics ────────────────────────────────────────────────────────
def test_metrics_consolidate_echo_snapshot():
    m = ws_metrics.build_metrics(_echo_snapshot(), run_id="ws-run-test")
    # one schema, all sections present
    for key in ("verdict", "structure", "cost", "latency", "by_agent",
                "quality", "pass_criteria"):
        assert key in m, f"metrics missing {key}"
    assert m["backend"] == "echo"
    # structure folded from ws_verdict
    s = m["structure"]
    assert s["delegation_channels_hit"] == 3
    assert s["a2a_channels_both_spoke"] == 2
    assert s["meta_leaks"] == 0
    assert s["deliverables_count"] == 2
    # echo → $0 cost, no calls
    assert m["cost"]["total_usd"] == 0.0
    assert m["cost"]["call_count"] == 0
    # no quality supplied → skipped, NOT counted against pass
    assert m["quality"]["status"] == "skipped"
    assert m["pass_criteria"]["quality_judged"] is False
    assert m["pass_criteria"]["overall_ok"] is True


def test_metrics_usage_from_inmemory_rows():
    snap = _echo_snapshot()
    snap["backend"] = "claude_cli"
    snap["usage"] = [
        {"agent_id": "coordinator", "model": "sonnet", "backend": "claude_cli",
         "est_cost": 0.012, "input_tokens": 1000, "output_tokens": 500,
         "estimated": 0, "latency_ms": 1200},
        {"agent_id": "researcher", "model": "sonnet", "backend": "claude_cli",
         "est_cost": 0.004, "input_tokens": 400, "output_tokens": 200,
         "estimated": 1, "latency_ms": 800},
    ]
    m = ws_metrics.build_metrics(snap, run_id="ws-run-test",
                                 quality=ws_judge.skipped("no CLI"))
    assert m["cost"]["total_usd"] == pytest.approx(0.016)
    assert m["cost"]["call_count"] == 2
    assert m["cost"]["estimated_count"] == 1
    assert m["latency"]["avg_ms"] == 1000  # (1200+800)/2
    # by_agent sorted by cost desc → coordinator first
    assert m["by_agent"][0]["agent_id"] == "coordinator"


def test_metrics_usage_from_served_aggregate():
    snap = _echo_snapshot()
    snap["backend"] = "claude_cli"
    snap["usage_aggregate"] = {
        "spend_month": 0.05, "call_count_month": 6, "input_tokens_month": 3000,
        "output_tokens_month": 1500, "estimated_count_month": 6,
        "avg_latency_ms": 1100,
        "by_agent": [{"agent_id": "coordinator", "total_cost": 0.03, "call_count": 3}],
    }
    m = ws_metrics.build_metrics(snap, run_id="ws-run-test")
    assert m["cost"]["total_usd"] == 0.05
    assert m["cost"]["source"] == "served_usage_api"
    assert m["latency"]["avg_ms"] == 1100
    assert m["by_agent"][0]["agent_id"] == "coordinator"


# ── baseline + regression ───────────────────────────────────────────────────────
def test_baseline_distill_and_no_regression():
    m = ws_metrics.build_metrics(_echo_snapshot(), run_id="ws-run-test")
    bl = ws_metrics.distill_baseline(m)
    assert bl["backend"] == "echo"
    assert bl["structure"]["delegation_channels_hit"] == 3
    # same run vs its own baseline → no regression
    trend = ws_metrics.compare_to_baseline(m, bl)
    assert trend["ok"] is True
    assert trend["is_regression"] is False


def test_regression_on_structural_drop():
    m = ws_metrics.build_metrics(_echo_snapshot(), run_id="ws-run-test")
    bl = ws_metrics.distill_baseline(m)
    bl["structure"]["delegation_channels_hit"] = 3  # baseline had 3
    # mutate current metrics to a worse run
    m["structure"]["delegation_channels_hit"] = 1
    trend = ws_metrics.compare_to_baseline(m, bl)
    assert trend["ok"] is False
    assert any("delegation" in r for r in trend["regressions"])


def test_regression_on_new_meta_leak():
    m = ws_metrics.build_metrics(_echo_snapshot(), run_id="ws-run-test")
    bl = ws_metrics.distill_baseline(m)  # 0 leaks
    m["structure"]["meta_leaks"] = 2
    trend = ws_metrics.compare_to_baseline(m, bl)
    assert trend["ok"] is False
    assert any("meta leaks" in r for r in trend["regressions"])


def test_regression_on_quality_drop():
    snap = _echo_snapshot()
    snap["backend"] = "claude_cli"
    good_q = {"status": "scored", "overall": 9.0, "pass": True, "scores": {},
              "rationale": "", "min_score": 7, "model": "m"}
    m_base = ws_metrics.build_metrics(snap, run_id="b", quality=good_q)
    bl = ws_metrics.distill_baseline(m_base)
    low_q = {**good_q, "overall": 6.0}
    m_cur = ws_metrics.build_metrics(snap, run_id="c", quality=low_q)
    trend = ws_metrics.compare_to_baseline(m_cur, bl, quality_threshold=1.0)
    assert trend["ok"] is False
    assert any("quality.overall" in r for r in trend["regressions"])


def test_regression_backend_mismatch_refused():
    m = ws_metrics.build_metrics(_echo_snapshot(), run_id="ws-run-test")
    bl = ws_metrics.distill_baseline(m)
    bl["backend"] = "claude_cli"  # mismatched
    trend = ws_metrics.compare_to_baseline(m, bl)
    assert trend["ok"] is False
    assert any("backend mismatch" in r for r in trend["regressions"])


# ── report rendering ────────────────────────────────────────────────────────────
def test_report_renders_echo_skeleton():
    m = ws_metrics.build_metrics(_echo_snapshot(), run_id="ws-run-test")
    md = ws_report.render_markdown(m, trend=None)
    assert "# Glimi Workspace — Run Report" in md
    assert "judge: skipped" in md  # honest skip note
    assert "Autonomous loop" in md
    assert "Cost & latency" in md
    assert "Pass criteria" in md
    assert "no baseline committed yet" in md  # no-trend note


def test_report_writes_pair(tmp_path):
    m = ws_metrics.build_metrics(_echo_snapshot(), run_id="ws-run-test")
    out = ws_report.write_report(m, trend=None, ts="testts", results_dir=tmp_path)
    md = tmp_path / "ws-report-testts.md"
    js = tmp_path / "ws-report-testts.json"
    assert md.exists() and js.exists()
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["metrics"]["run_id"] == "ws-run-test"
    assert out["md"].endswith("ws-report-testts.md")


def test_generate_from_snapshot_echo_skips_judge(tmp_path):
    # The full orchestration on an echo snapshot must SKIP the judge (no CLI spawn)
    # and still produce the report pair — the FAST self-test path.
    out = ws_report.generate_from_snapshot(
        _echo_snapshot(), run_id="ws-run-test", results_dir=tmp_path,
        baseline_path=tmp_path / "nope.json",  # absent → no trend
    )
    assert out["quality"]["status"] == "skipped"
    assert "echo" in out["quality"]["rationale"]
    assert out["metrics"]["pass_criteria"]["overall_ok"] is True


# ── DYNAMIC roster (manager proposes a goal-fit team, not researcher/builder/critic) ─
def _dynamic_roster_snapshot() -> dict:
    """A claude_cli run where the manager built a CUSTOM roster (culture-coach /
    dev-lead / hr-designer) with goal-fit channel names. The verdict must DERIVE
    the delegation/A2A channels + specialists from the snapshot, not the old fixed
    researcher/builder/critic roster. The real deliverable is the LONGEST
    coordinator message in dm-coordinator (a structured document); the synthesized
    drive_result.last_deliverable is a short ack the verdict must NOT use as 'last'.
    """
    coord = "coordinator"
    n = [0]

    def msg(speaker, text):
        n[0] += 1
        return {"id": n[0], "speaker": speaker, "message": text,
                "timestamp": "2026-06-22T00:00:00+00:00"}

    doc = ("# 온보딩 체크리스트\n\n## 첫날\n- 계정 발급\n- 장비 세팅\n"
           "1. 팀 소개\n2. 코드베이스 투어\n\n## 첫주\n- 첫 PR 머지\n" + "추가 설명 " * 80)
    return {
        "run_id": "ws-e2e-dyn",
        "backend": "claude_cli",
        "goal": "신입 온보딩 체크리스트",
        "context": "맥락",
        "owner_id": "owner",
        "elapsed_seconds": 120.0,
        "error": None,
        "rounds_requested": 2,
        # served path → in-memory rows unreachable; aggregate carries spend.
        "usage": [],
        "usage_aggregate": {"spend_month": 0.05, "call_count_month": 30,
                            "input_tokens_month": 3000, "output_tokens_month": 1500,
                            "estimated_count_month": 30, "avg_latency_ms": 1500,
                            "by_agent": []},
        "channels": {
            "dm-coordinator": [
                msg("owner", "온보딩 체크리스트 만들어줘"),
                msg(coord, "네, 계획 세울게요"),          # short ack
                msg("owner", "이제 문서로 정리해줘"),
                msg(coord, doc),                            # the REAL deliverable (longest)
            ],
            "dm-culture-coach": [msg(coord, "문화 관점 정리 부탁"), msg("culture-coach", "ok 문화 부분")],
            "dm-dev-lead": [msg(coord, "개발 환경 항목 부탁"), msg("dev-lead", "ok 개발 부분")],
            "dm-hr-designer": [msg(coord, "행정 항목 부탁"), msg("hr-designer", "ok 행정 부분")],
            "internal-culture-coach-hr-designer": [
                msg("culture-coach", "이건 어때요"), msg("culture-coach", "보강했어요"),
                msg("hr-designer", "좋아요"), msg("hr-designer", "추가할게요")],
            "internal-dev-lead-culture-coach": [
                msg("dev-lead", "환경 부분"), msg("dev-lead", "정리됨"),
                msg("culture-coach", "맞춰볼게요"), msg("culture-coach", "반영함")],
            "internal-owner": [msg("owner", "검토 1"), msg("owner", "검토 2")],
        },
        # The served harness synthesizes this; last_deliverable is the LAST coord
        # message which happens to be the long doc here, but the verdict measures
        # the LONGEST coordinator message regardless.
        "drive_result": {
            "rounds": 2,
            "deliverables": ["네, 계획 세울게요", doc],
            "last_deliverable": doc,
            "done": False,
            "stopped_reason": "max_rounds",
        },
    }


def test_verdict_dynamic_roster_delegation_and_a2a_derived():
    # The verdict must NOT FAIL just because the roster isn't researcher/builder/critic.
    snap = _dynamic_roster_snapshot()
    v = ws_verdict.judge_snapshot(snap, run_id="ws-e2e-dyn")
    m = v["metrics"]
    # delegation derived from dm-* (≠ dm-coordinator) — coordinator spoke into all 3.
    assert set(m["delegation_by_channel"]) == {
        "dm-culture-coach", "dm-dev-lead", "dm-hr-designer"}
    assert all(c > 0 for c in m["delegation_by_channel"].values())
    assert not any(i["category"] == "delegation" for i in v["issues"])
    # a2a derived from internal-* (≠ internal-owner): both internal channels have
    # ≥2 distinct non-owner speakers each ≥2 messages (claude_cli → min_each=2).
    assert set(m["a2a_by_channel"]) == {
        "internal-culture-coach-hr-designer", "internal-dev-lead-culture-coach"}
    assert not any(i["category"] == "a2a" for i in v["issues"])
    assert m["a2a_min_each_required"] == 2


def test_verdict_dynamic_roster_deliverable_is_longest_coord_msg():
    # The REAL deliverable = LONGEST coordinator message in dm-coordinator (the doc),
    # NOT the short ack at index 0. goal_advanced True (substantial + structured).
    snap = _dynamic_roster_snapshot()
    v = ws_verdict.judge_snapshot(snap, run_id="ws-e2e-dyn")
    m = v["metrics"]
    assert m["deliverable_len_first"] < 50            # the short ack
    assert m["deliverable_len_last"] > 400            # the long structured doc
    assert m["deliverable_has_structure"] is True
    assert m["goal_advanced"] is True
    assert v["status"] in ("PASS", "WARN")            # never FAIL on a great run


def test_verdict_wall_cap_envelope_is_soft_not_blocker():
    # A wall-clock-cap timeout in snap['error'] is a runner-ENVELOPE condition →
    # soft DRIFT, never a BLOCKER (a real run can still be excellent).
    snap = _dynamic_roster_snapshot()
    snap["error"] = "wall_clock_cap 1800.0s exceeded"
    v = ws_verdict.judge_snapshot(snap, run_id="ws-e2e-dyn")
    envelope = [i for i in v["issues"] if i["category"] == "runner_envelope"]
    assert len(envelope) == 1
    assert envelope[0]["severity"] == "DRIFT"
    assert not any(i["severity"] == "BLOCKER" for i in v["issues"])
    assert v["status"] == "WARN"

    # A genuine runner crash is still a BLOCKER → FAIL.
    snap["error"] = "RuntimeError: boom"
    v2 = ws_verdict.judge_snapshot(snap, run_id="ws-e2e-dyn")
    assert any(i["severity"] == "BLOCKER" and i["category"] == "error"
               for i in v2["issues"])
    assert v2["status"] == "FAIL"


def test_metrics_dynamic_roster_structure_counts():
    # ws_metrics folds the derived structure correctly for a 3-specialist roster.
    m = ws_metrics.build_metrics(_dynamic_roster_snapshot(), run_id="ws-e2e-dyn")
    s = m["structure"]
    assert s["delegation_channels_hit"] == 3
    assert s["a2a_channels_both_spoke"] == 2
    assert s["deliverable_len_last"] > 400
    assert s["goal_advanced"] is True
