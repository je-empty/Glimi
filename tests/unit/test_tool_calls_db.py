"""tool_calls 테이블 + SqliteKernelStore 관측 메서드 + 마이그레이션 멱등성.

검증:
  - SqliteKernelStore.record_tool_call / recent_tool_calls roundtrip (필터·정렬 포함)
  - created_at 은 UTC-aware ISO (now_utc_iso, +00:00 꼬리)
  - init_db 두 번 호출 멱등
  - tool_calls 테이블 없던 pre-feature DB 가 _migrate_schema 로 백필 없이 안전 업그레이드
  - KernelStore 베이스 no-op (관측 미지원 store) 는 0 / [] 로 graceful degrade

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_tool_calls_db.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from src import db
from src.adapters.kernel_store import SqliteKernelStore
from glimi.store import KernelStore


@pytest.fixture()
def store(tmp_path):
    """Fresh temp DB + SqliteKernelStore."""
    saved = db.DB_PATH
    db.DB_PATH = str(tmp_path / "community.db")
    db.init_db()
    try:
        yield SqliteKernelStore()
    finally:
        db.DB_PATH = saved


# ── record / query roundtrip ──────────────────────────────────────────

def test_record_and_recent_roundtrip(store):
    rid = store.record_tool_call(
        agent_id="agent-1", agent_type="mgr", channel="mgr-log",
        tool_name="create_room", args_json='{"name":"x"}',
        result_preview='{"created":true}', ok=True, latency_ms=42,
    )
    assert rid >= 1
    rows = store.recent_tool_calls(limit=10)
    assert len(rows) == 1
    r = rows[0]
    assert r["tool_name"] == "create_room"
    assert r["agent_id"] == "agent-1"
    assert r["agent_type"] == "mgr"
    assert r["channel"] == "mgr-log"
    assert r["ok"] == 1
    assert r["latency_ms"] == 42
    assert r["args_json"] == '{"name":"x"}'
    assert r["result_preview"] == '{"created":true}'


def test_created_at_is_utc_aware_iso(store):
    store.record_tool_call(tool_name="ping", ok=True)
    row = store.recent_tool_calls(limit=1)[0]
    # now_utc_iso() yields a +00:00 (or +00:00-style) tz-aware ISO string.
    assert row["created_at"].endswith("+00:00")


def test_failed_call_records_ok_zero(store):
    store.record_tool_call(tool_name="bad", result_preview="unknown tool", ok=False)
    row = store.recent_tool_calls(limit=1)[0]
    assert row["ok"] == 0
    assert row["result_preview"] == "unknown tool"


def test_recent_orders_newest_first_and_limits(store):
    for i in range(5):
        store.record_tool_call(tool_name=f"t{i}", ok=True)
    rows = store.recent_tool_calls(limit=3)
    assert len(rows) == 3
    # newest first (id DESC) — last inserted t4 leads.
    assert [r["tool_name"] for r in rows] == ["t4", "t3", "t2"]


def test_recent_filters_by_agent(store):
    store.record_tool_call(agent_id="a", tool_name="x", ok=True)
    store.record_tool_call(agent_id="b", tool_name="y", ok=True)
    rows = store.recent_tool_calls(agent_id="b")
    assert len(rows) == 1 and rows[0]["tool_name"] == "y"


# ── base-class no-op (observability-unaware store) ────────────────────

class _BareStore(KernelStore):
    """A KernelStore subclass that does NOT override the observability methods —
    proves the concrete base defaults keep an old/partial store safe."""

    # Implement the abstract methods minimally so it instantiates.
    def set_channel_status(self, *a, **k): ...
    def increment_channel_turn(self, *a, **k): return 0
    def get_recent_messages(self, *a, **k): return []
    def get_messages_by_range(self, *a, **k): return []
    def get_agent(self, *a, **k): return None
    def list_agents(self, *a, **k): return []
    def get_channel_participants(self, *a, **k): return []
    def get_channel_overview(self, *a, **k): return []
    def get_agent_model_override(self, *a, **k): return None
    def log_message(self, *a, **k): return None
    def add_message_hook(self, *a, **k): ...
    def add_reaction(self, *a, **k): return False
    def remove_reaction(self, *a, **k): ...
    def get_reactions(self, *a, **k): return []
    def get_reactions_for(self, *a, **k): return {}
    def set_reply(self, *a, **k): ...
    def get_thread(self, *a, **k): return []
    def get_recent_events(self, *a, **k): return []
    def get_agent_channels(self, *a, **k): return []
    def get_memory_coverage(self, *a, **k): return {}
    def get_agent_by_name(self, *a, **k): return None
    def get_relationship(self, *a, **k): return None
    def get_relationship_history(self, *a, **k): return []
    def update_intimacy(self, *a, **k): ...
    def add_relationship_delta(self, *a, **k): return 0
    def get_memories(self, *a, **k): return []
    def get_latest_memory(self, *a, **k): return None
    def get_pinned_memories(self, *a, **k): return []
    def add_memory(self, *a, **k): return 0
    def set_pin(self, *a, **k): ...
    def touch_memory_access(self, *a, **k): ...
    def count_messages_after(self, *a, **k): return 0
    def get_facts(self, *a, **k): return []
    def add_fact(self, *a, **k): return 0
    def list_users(self, *a, **k): return []
    def set_relationship_dynamics(self, *a, **k): ...
    def get_agent_emotion(self, *a, **k): return None
    def set_agent_emotion(self, *a, **k): ...
    def get_uncovered_memories(self, *a, **k): return []
    def get_memories_across_channels(self, *a, **k): return []
    def get_recent_messages_across_channels(self, *a, **k): return []
    def search_memories(self, *a, **k): return []
    def get_memory(self, *a, **k): return None
    def get_memory_stats(self, *a, **k): return {}


def test_base_store_observability_is_safe_noop():
    s = _BareStore()
    assert s.record_tool_call(tool_name="x", ok=True) == 0
    assert s.recent_tool_calls() == []


# ── migration idempotency ─────────────────────────────────────────────

def test_init_db_twice_is_idempotent(store):
    db.init_db()
    db.init_db()
    rid = store.record_tool_call(tool_name="after-reinit", ok=True)
    assert rid >= 1


def test_migration_upgrades_pre_feature_db(tmp_path):
    """Simulate an OLD community DB WITHOUT the tool_calls table. _migrate_schema
    must create it with NO backfill, and the DB stays functional. Mirrors the
    reactions migration test."""
    saved = db.DB_PATH
    path = str(tmp_path / "old.db")
    db.DB_PATH = path
    try:
        db.init_db()  # full current schema

        # Rewind: drop the tool_calls table + its indexes (pre-feature snapshot).
        conn = sqlite3.connect(path)
        conn.executescript("""
            DROP INDEX IF EXISTS idx_toolcall_created;
            DROP INDEX IF EXISTS idx_toolcall_agent;
            DROP TABLE IF EXISTS tool_calls;
        """)
        conn.commit()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "tool_calls" not in tables
        conn.close()

        # Run the migration — must re-create the table.
        db._migrate_schema()

        conn = sqlite3.connect(path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "tool_calls" in tables
        conn.close()

        # Idempotent — second migrate no-ops.
        db._migrate_schema()

        # Functional after upgrade.
        s = SqliteKernelStore()
        rid = s.record_tool_call(tool_name="post-migrate", ok=True)
        assert rid >= 1
        assert s.recent_tool_calls(limit=1)[0]["tool_name"] == "post-migrate"
    finally:
        db.DB_PATH = saved
