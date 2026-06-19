"""Tests for the Workspace live demo (apps/workspace/demo.py) and the in-memory
store's observability methods that back the dashboard's usage / tool-timeline panels.

Kernel-only: imports `glimi` + the app's `demo` module, never `src` / Discord.
"""
from __future__ import annotations

import os
import sys
import threading

import pytest

# Make the flat-dir app modules (demo, team) importable like run.py does.
_WS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "apps", "workspace")
if _WS_DIR not in sys.path:
    sys.path.insert(0, _WS_DIR)

import demo  # noqa: E402
from glimi.dashboard import DashboardReader  # noqa: E402
from glimi.stores.memory import InMemoryKernelStore  # noqa: E402


# ── the seeded demo population ───────────────────────────────────────────────

@pytest.fixture()
def built():
    return demo.build()


def test_build_population(built):
    r = DashboardReader(built.store)
    snap = r.snapshot()
    # Coordinator + 3 specialists.
    assert len(snap["agents"]) == 4
    ids = {a["id"] for a in snap["agents"]}
    assert ids == {"coordinator", "researcher", "builder", "critic"}
    # The full interaction web: 3 DMs + owner DM + 2 A2A + group + approvals = 8.
    channels = {c["channel"] for c in snap["channels"]}
    assert channels == {
        "dm-coordinator", "dm-researcher", "dm-builder", "dm-critic",
        "internal-researcher-critic", "internal-builder-researcher",
        "group-team", "mgr-approvals",
    }
    # Every relationship edge the graph draws (lead + 3 manages + 2 collaborator).
    assert len(snap["relationships"]) == 6
    types = sorted(e["type"] for e in snap["relationships"])
    assert types == ["collaborator", "collaborator", "lead", "manages", "manages", "manages"]


def test_coordinator_is_hub_and_mgr(built):
    r = DashboardReader(built.store)
    agents = {a["id"]: a for a in r.snapshot()["agents"]}
    assert agents["coordinator"]["type"] == "mgr"
    # Coordinator is the most-connected node (owner + 3 specialists = 4 edges).
    detail = r.agent_detail("coordinator")
    assert len(detail["relationships"]) == 4


def test_memory_facts_emotions_seeded(built):
    r = DashboardReader(built.store)
    critic = r.agent_detail("critic")
    assert critic["emotion"]   # an emotion is seeded (content/language-agnostic)
    assert len(critic["pinned_memories"]) >= 1
    assert any(f for f in critic["facts"])  # a semantic fact exists


def test_approval_trail_present(built):
    from glimi.dashboard.app import _channel_detail
    r = DashboardReader(built.store)
    appr = _channel_detail(r, "mgr-approvals")
    # The HITL trail seeds the proposed → approved → outcome stages (content/
    # language-agnostic: assert the multi-stage trail exists, not exact prose).
    assert len(appr["messages"]) >= 3
    assert " ".join(m.get("message", "") for m in appr["messages"]).strip()


def test_usage_panel_honest_and_populated(built):
    r = DashboardReader(built.store)
    u = r.usage()
    # One usage row per agent turn — populated, all echo/local at $0, all estimated.
    assert u["call_count_month"] > 0
    assert u["estimated_count_month"] == u["call_count_month"]
    assert u["spend_month"] == 0.0  # echo/local is free — no fabricated dollars
    assert u["input_tokens_month"] > 0 and u["output_tokens_month"] > 0
    by_agent = {a["agent_id"]: a for a in u["by_agent"]}
    assert "coordinator" in by_agent


def test_tool_timeline_populated(built):
    r = DashboardReader(built.store)
    tl = r.tool_timeline()
    assert len(tl) >= 3
    names = {t["tool_name"] for t in tl}
    assert "recall_memory" in names
    assert all(t.get("created_at") for t in tl)  # newest-first, timestamped


# ── live activity loop ───────────────────────────────────────────────────────

def test_activity_loop_unfolds_then_heartbeats(built):
    r = DashboardReader(built.store)
    calls_before = r.usage()["call_count_month"]
    msgs_before = sum(c.get("msg_count", 0) for c in r.snapshot()["channels"])

    stop = threading.Event()
    t = threading.Thread(target=demo.activity_loop, args=(built, stop, 0.02), daemon=True)
    t.start()
    # Long enough to unfold the whole continuation + a few heartbeats.
    import time
    time.sleep(0.6)
    stop.set()
    t.join(timeout=1.0)

    after = r.usage()
    msgs_after = sum(c.get("msg_count", 0) for c in r.snapshot()["channels"])
    assert after["call_count_month"] > calls_before  # usage keeps ticking
    assert msgs_after > msgs_before                   # the continuation added turns


def test_activity_loop_stops_promptly(built):
    stop = threading.Event()
    t = threading.Thread(target=demo.activity_loop, args=(built, stop, 0.01), daemon=True)
    t.start()
    stop.set()
    t.join(timeout=1.0)
    assert not t.is_alive()


# ── in-memory store observability methods (mirror SqliteKernelStore) ──────────

def test_inmemory_record_and_read_tool_calls():
    s = InMemoryKernelStore()
    rid = s.record_tool_call(agent_id="a1", tool_name="recall_memory",
                             args_json='{"q":"x"}', result_preview="2 hits",
                             ok=True, latency_ms=12)
    assert rid == 1
    s.record_tool_call(agent_id="a2", tool_name="remember", ok=False, latency_ms=3)
    rows = s.recent_tool_calls(limit=10)
    assert [r["tool_name"] for r in rows] == ["remember", "recall_memory"]  # newest first
    assert s.recent_tool_calls(agent_id="a1")[0]["ok"] == 1
    assert s.recent_tool_calls(agent_id="a2")[0]["ok"] == 0


def test_inmemory_usage_spend_and_by_agent():
    s = InMemoryKernelStore()
    s.record_usage(agent_id="a1", agent_type="mgr", model="echo", backend="echo",
                   input_tokens=100, output_tokens=50, est_cost=0.0,
                   estimated=True, latency_ms=200)
    s.record_usage(agent_id="a1", agent_type="mgr", model="echo", backend="echo",
                   input_tokens=20, output_tokens=10, est_cost=0.0,
                   estimated=True, latency_ms=100)
    s.record_usage(agent_id="a2", agent_type="persona", model="sonnet",
                   backend="anthropic", input_tokens=1000, output_tokens=500,
                   est_cost=0.0105, estimated=False, latency_ms=900)
    spend = s.usage_spend()
    assert spend["call_count"] == 3
    assert spend["estimated_count"] == 2
    assert spend["input_tokens"] == 1120
    assert abs(spend["total_cost"] - 0.0105) < 1e-9
    assert spend["avg_latency_ms"] == 400  # (200+100+900)/3
    by_agent = {a["agent_id"]: a for a in s.usage_by_agent()}
    assert by_agent["a1"]["call_count"] == 2
    assert by_agent["a2"]["total_cost"] == pytest.approx(0.0105)


def test_inmemory_usage_time_filter():
    s = InMemoryKernelStore()
    s.record_usage(agent_id="a1", backend="echo", input_tokens=1,
                   ts="2020-01-01T00:00:00+00:00")
    s.record_usage(agent_id="a1", backend="echo", input_tokens=1,
                   ts="2999-01-01T00:00:00+00:00")
    # since a future-but-past boundary: only the year-2999 row counts.
    spend = s.usage_spend(since="2500-01-01T00:00:00+00:00")
    assert spend["call_count"] == 1
