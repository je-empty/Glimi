"""glimi/dashboard 단위 테스트 — store 기반 DashboardReader (대시보드 디커플링 P1.0).

검증:
  - DashboardReader 는 KernelStore 만으로 agent population 을 읽어낸다 (web/Discord/DB 무관)
  - agents() / agent_detail() / channels() / snapshot() 가 monitor 와 호환되는 shape 반환
  - glimi.dashboard import 가 web deps (fastapi/jinja/pydantic/discord) 를 끌어오지 않음
  - sparse / 미존재 데이터에서도 crash 없이 빈 결과로 degrade

zero-dep 보장: echo backend (오프라인) 만 사용 — LLM/네트워크 호출 없음.

주의: Glimi() 생성자는 _runtime/_memory 모듈 전역 + GLIMI_LLM_BACKEND env 를
주입한다. fixture teardown 에서 전부 복원한다.

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_dashboard.py -q
"""
from __future__ import annotations

import os
import sys

import pytest

from glimi import Glimi
from glimi.dashboard import DashboardReader

# Worktree root (<wt>/tests/unit/this_file → up 3) — so the purity subprocess can
# resolve this checkout's ``glimi`` regardless of where pytest is invoked from.
_WORKTREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ────────────────────────────────────────────────────
# fixture — population 구축 + 전역 복원
# ────────────────────────────────────────────────────

@pytest.fixture
def population():
    """alice/bob 두 에이전트 population + 약간의 대화/메모리/관계 데이터.

    teardown 에서 Glimi 가 주입한 커널 전역 (_runtime/_memory) + env 를 복원.
    """
    from glimi import memory as _memory
    from glimi import runtime as _runtime

    saved = {
        "r_store": _runtime._store, "r_profiles": _runtime._profiles,
        "r_owner": _runtime._owner, "r_observer": _runtime._observer,
        "m_store": _memory._store, "m_profiles": _memory._profiles,
        "m_owner": _memory._owner, "m_observer": _memory._observer,
        "env": os.environ.get("GLIMI_LLM_BACKEND"),
    }

    g = Glimi(backend="echo", owner_name="Owner", owner_id="owner")
    g.add_agent("alice", name="Alice", persona="A curious, upbeat companion.")
    g.add_agent("bob", name="Bob", persona="A calm, thoughtful friend.")
    # 대화 생성 (메모리 추출 hook + 채널/coverage 데이터 채움)
    g.reply("alice", "hi", channel="room")
    # 직접 store 에 메모리/사실/관계 시드 — reader 가 읽어낼 데이터 보장
    g.store.add_memory("alice", "room", level=1, content="Owner said hi in room.",
                       msg_id_from=1, msg_id_to=2, msg_count=2, importance=6)
    g.store.add_memory("alice", "room", level=2, content="Alice met Owner.",
                       msg_id_to=2, importance=7, is_pinned=True)
    g.store.add_fact("alice", subject="Owner", predicate="likes", object_value="coffee")
    g.store.set_relationship("alice", "owner", rel_type="friend", intimacy=42,
                             dynamics="warm")

    yield g

    # 전역 복원
    _runtime.set_store(saved["r_store"]); _runtime.set_profiles(saved["r_profiles"])
    _runtime.set_owner(saved["r_owner"]); _runtime.set_observer(saved["r_observer"])
    _memory.set_store(saved["m_store"]); _memory.set_profiles(saved["m_profiles"])
    _memory.set_owner(saved["m_owner"]); _memory.set_observer(saved["m_observer"])
    if saved["env"] is None:
        os.environ.pop("GLIMI_LLM_BACKEND", None)
    else:
        os.environ["GLIMI_LLM_BACKEND"] = saved["env"]


# ────────────────────────────────────────────────────
# 구성 / 입력 검증
# ────────────────────────────────────────────────────

def test_requires_store():
    with pytest.raises(ValueError):
        DashboardReader(None)


# ────────────────────────────────────────────────────
# agents()
# ────────────────────────────────────────────────────

def test_agents_lists_population(population):
    r = DashboardReader(population.store)
    agents = r.agents()
    ids = {a["id"] for a in agents}
    assert {"alice", "bob"} <= ids
    by_id = {a["id"]: a for a in agents}
    assert by_id["alice"]["name"] == "Alice"
    assert by_id["bob"]["name"] == "Bob"
    # 기본 display 키 존재
    for a in agents:
        assert set(a) >= {"id", "name", "type", "status", "model_override",
                          "emotion", "intensity", "last_active"}


def test_agents_emotion_from_store(population):
    population.store.set_agent_emotion("alice", "신남", 8)
    r = DashboardReader(population.store)
    alice = next(a for a in r.agents() if a["id"] == "alice")
    assert alice["emotion"] == "신남"
    assert alice["intensity"] == 8


# ────────────────────────────────────────────────────
# agent_detail()
# ────────────────────────────────────────────────────

def test_agent_detail_shape(population):
    r = DashboardReader(population.store)
    d = r.agent_detail("alice")
    # profile basics + 5-layer 메모리 + facts + relationships + channels + coverage
    for key in ("id", "name", "type", "channels", "memory_coverage",
                "memories_by_channel", "pinned_memories", "facts", "relationships"):
        assert key in d, f"missing key: {key}"
    assert d["id"] == "alice"
    assert d["name"] == "Alice"


def test_agent_detail_memory_layers(population):
    r = DashboardReader(population.store)
    d = r.agent_detail("alice")
    room = d["memories_by_channel"].get("room")
    assert room is not None, "room channel memories should be present"
    # 시드한 L1 + L2 메모리가 레벨별로 노출되어야 함
    assert 1 in room["levels"]
    assert 2 in room["levels"]
    assert any(m["content"] == "Owner said hi in room." for m in room["levels"][1])
    # pinned 메모리 + 사실 + 관계
    assert any(m.get("is_pinned") for m in d["pinned_memories"])
    assert any(f["subject"] == "Owner" for f in d["facts"])
    assert any(rel["other_id"] == "owner" and rel["intimacy"] == 42
               for rel in d["relationships"])


def test_agent_detail_unknown(population):
    r = DashboardReader(population.store)
    d = r.agent_detail("nobody")
    assert d.get("error") == "agent not found"


# ────────────────────────────────────────────────────
# channels()
# ────────────────────────────────────────────────────

def test_channels_includes_room(population):
    r = DashboardReader(population.store)
    chans = r.channels()
    names = {c.get("channel") for c in chans}
    assert "room" in names
    room = next(c for c in chans if c.get("channel") == "room")
    assert "participants" in room


# ────────────────────────────────────────────────────
# snapshot()
# ────────────────────────────────────────────────────

def test_snapshot_keys(population):
    r = DashboardReader(population.store)
    snap = r.snapshot()
    assert set(snap) >= {"agents", "channels", "relationships"}
    assert {a["id"] for a in snap["agents"]} >= {"alice", "bob"}
    assert "room" in {c.get("channel") for c in snap["channels"]}
    # 관계 엣지: alice↔owner (intimacy 42) 가 source/target 형태로 나와야 함
    edge = next((e for e in snap["relationships"]
                 if {e["source"], e["target"]} == {"alice", "owner"}), None)
    assert edge is not None
    assert edge["intimacy"] == 42
    assert edge["type"] == "friend"


# ────────────────────────────────────────────────────
# graceful degradation — sparse store
# ────────────────────────────────────────────────────

def test_empty_store_does_not_crash():
    from glimi.stores.memory import InMemoryKernelStore
    r = DashboardReader(InMemoryKernelStore())
    assert r.agents() == []
    assert r.channels() == []
    snap = r.snapshot()
    assert snap == {"agents": [], "channels": [], "relationships": []}
    assert r.agent_detail("ghost").get("error") == "agent not found"


# ────────────────────────────────────────────────────
# zero-dep purity — import pulls in no web deps
# ────────────────────────────────────────────────────

def test_dashboard_import_has_no_web_deps():
    """glimi.dashboard 를 import 해도 web/Discord 모듈이 끌려오지 않아야 한다
    (kernel zero-dep 보장).

    같은 pytest 세션의 다른 테스트가 이미 fastapi/discord 등을 sys.modules 에
    올려놨을 수 있으므로, 깨끗한 subprocess 에서 import 해서 검사한다 — 이게
    'glimi.dashboard 단독 import 가 web deps 를 끌어오는가' 의 진짜 검증.
    """
    import subprocess

    code = (
        "import sys; import glimi.dashboard; from glimi.dashboard import DashboardReader; "
        "forbidden={'fastapi','pydantic','jinja2','discord','starlette','uvicorn'}; "
        "leaked=forbidden & set(sys.modules); "
        "print('LEAKED:'+','.join(sorted(leaked)) if leaked else 'CLEAN')"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [_WORKTREE, env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env,
    )
    out = proc.stdout.strip()
    assert proc.returncode == 0, f"import failed: {proc.stderr}"
    assert out == "CLEAN", f"glimi.dashboard pulled in web deps: {out}"


# ────────────────────────────────────────────────────
# observability — tool_timeline() / usage()
# (DashboardReader 가 store 의 신규 관측 메서드를 surface)
# ────────────────────────────────────────────────────

@pytest.fixture()
def obs_store(tmp_path):
    """SqliteKernelStore over a fresh temp DB — implements the observability
    methods (the in-memory population store keeps the base no-ops, which the
    degrade tests below exercise separately)."""
    from src import db
    from src.adapters.kernel_store import SqliteKernelStore
    saved = db.DB_PATH
    db.DB_PATH = str(tmp_path / "obs.db")
    db.init_db()
    try:
        yield SqliteKernelStore()
    finally:
        db.DB_PATH = saved


def test_tool_timeline_returns_recorded_calls(obs_store):
    obs_store.record_tool_call(agent_id="alice", agent_type="mgr",
                               channel="mgr-log", tool_name="create_room",
                               args_json='{"name":"x"}', result_preview="ok",
                               ok=True, latency_ms=12)
    r = DashboardReader(obs_store)
    rows = r.tool_timeline(limit=10)
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "create_room"
    assert rows[0]["latency_ms"] == 12
    assert rows[0]["ok"] == 1


def test_tool_timeline_filters_by_agent(obs_store):
    obs_store.record_tool_call(agent_id="alice", tool_name="x", ok=True)
    obs_store.record_tool_call(agent_id="bob", tool_name="y", ok=True)
    r = DashboardReader(obs_store)
    rows = r.tool_timeline(agent_id="bob")
    assert len(rows) == 1 and rows[0]["tool_name"] == "y"


def test_usage_returns_spend_view(obs_store):
    obs_store.record_usage(agent_id="alice", agent_type="memory_extract",
                           model="claude-haiku-4-5", backend="anthropic_sdk",
                           input_tokens=1000, output_tokens=200,
                           est_cost=0.002, estimated=False, latency_ms=300)
    obs_store.record_usage(agent_id="bob", agent_type="persona",
                           model="claude-haiku-4-5", backend="claude_cli",
                           input_tokens=500, output_tokens=100,
                           est_cost=0.001, estimated=True, latency_ms=900)
    r = DashboardReader(obs_store)
    u = r.usage()
    # shape
    for key in ("as_of", "pricing_as_of", "spend_today", "spend_month",
                "call_count_month", "estimated_count_month", "avg_latency_ms",
                "by_agent"):
        assert key in u, f"missing usage key: {key}"
    assert u["call_count_month"] == 2
    assert u["estimated_count_month"] == 1  # only the CLI row is estimated
    assert abs(u["spend_month"] - 0.003) < 1e-9
    assert len(u["by_agent"]) == 2
    assert u["pricing_as_of"]  # surfaced so stale rates are visible


def test_reader_degrades_on_store_without_observability(population):
    """The in-memory population store keeps the base no-op observability methods —
    the reader must surface empty/zeroed data, never raise."""
    r = DashboardReader(population.store)
    assert r.tool_timeline() == []
    u = r.usage()
    assert u["call_count_month"] == 0
    assert u["spend_month"] == 0.0
    assert u["by_agent"] == []
