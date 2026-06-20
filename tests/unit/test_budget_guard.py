"""Budget guard — monthly USD soft cap that degrades Claude routing to local.

Covers:
  - allow_claude: cap=0/unset → True; spend over cap → False; under → True
  - the ~15s spend cache invalidates on record_usage (in-memory + sqlite)
  - _provider_for diverts a 'claude' decision over cap → 'ollama' (local avail)
    or '__capped__' (no local), and stays 'claude' when within budget/unset
  - the facade (generate/stream_lines) forces non-Claude / empty over cap and
    records was_blocked=True
  - was_blocked persists in both SqliteKernelStore and InMemoryKernelStore

Run:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_budget_guard.py -q
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from glimi import budget
from glimi import runtime as kr
from glimi import llm
from glimi import InMemoryKernelStore
from glimi.llm.base import LLMResponse


def _this_month_ts() -> str:
    """A ts inside the current UTC month (so it counts toward month-to-date spend)."""
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=12, minute=0, second=0, microsecond=0).isoformat()


@pytest.fixture()
def mem_store():
    """In-memory store wired as the kernel store, with a clean budget cache and a
    reset active-community contextvar (other test files leave it dirty via the
    platform community switch)."""
    saved = kr._store
    saved_cid = kr.community_id()
    s = InMemoryKernelStore()
    kr.set_store(s)
    kr.set_active_community(None)
    budget.invalidate()
    try:
        yield s
    finally:
        kr.set_store(saved)
        kr.set_active_community(saved_cid)
        budget.invalidate()


@pytest.fixture()
def no_cap(monkeypatch):
    monkeypatch.delenv("GLIMI_MONTHLY_CAP_USD", raising=False)


# ── allow_claude: cap configuration ───────────────────────────────────

def test_unset_cap_allows(mem_store, monkeypatch):
    monkeypatch.delenv("GLIMI_MONTHLY_CAP_USD", raising=False)
    assert budget.allow_claude(None) is True


def test_zero_or_negative_cap_allows(mem_store, monkeypatch):
    for raw in ("0", "0.0", "-5", "  ", "garbage"):
        monkeypatch.setenv("GLIMI_MONTHLY_CAP_USD", raw)
        budget.invalidate()
        assert budget.allow_claude(None) is True, raw


def test_no_store_degrades_open(monkeypatch):
    saved = kr._store
    kr.set_store(None)
    budget.invalidate()
    monkeypatch.setenv("GLIMI_MONTHLY_CAP_USD", "0.01")
    try:
        # Can't measure spend → never block.
        assert budget.allow_claude(None) is True
    finally:
        kr.set_store(saved)
        budget.invalidate()


# ── allow_claude: spend vs cap ────────────────────────────────────────

def test_under_cap_allows(mem_store, monkeypatch):
    monkeypatch.setenv("GLIMI_MONTHLY_CAP_USD", "1.00")
    mem_store.record_usage(model="claude-opus-4-8", backend="anthropic_sdk",
                           est_cost=0.50, ts=_this_month_ts())
    assert budget.allow_claude(None) is True


def test_over_cap_blocks(mem_store, monkeypatch):
    monkeypatch.setenv("GLIMI_MONTHLY_CAP_USD", "0.01")
    mem_store.record_usage(model="claude-opus-4-8", backend="anthropic_sdk",
                           est_cost=1.00, ts=_this_month_ts())
    assert budget.allow_claude(None) is False


def test_spend_is_per_community(mem_store, monkeypatch):
    monkeypatch.setenv("GLIMI_MONTHLY_CAP_USD", "0.01")
    mem_store.record_usage(model="m", backend="anthropic_sdk", est_cost=1.0,
                           community="rich", ts=_this_month_ts())
    assert budget.allow_claude("rich") is False
    assert budget.allow_claude("poor") is True  # separate community → no spend


# ── cache invalidation on record_usage ────────────────────────────────

def test_cache_invalidates_on_record(mem_store, monkeypatch):
    monkeypatch.setenv("GLIMI_MONTHLY_CAP_USD", "1.00")
    assert budget.allow_claude(None) is True          # primes cache (spend 0)
    mem_store.record_usage(model="m", backend="anthropic_sdk",
                           est_cost=2.0, ts=_this_month_ts())
    # record_usage invalidated the cache → next check sees the new spend.
    assert budget.allow_claude(None) is False


# ── Guard point 1: _provider_for ──────────────────────────────────────

def test_provider_for_claude_when_unset(mem_store, monkeypatch):
    monkeypatch.delenv("GLIMI_MONTHLY_CAP_USD", raising=False)
    monkeypatch.delenv("GLIMI_LLM_BACKEND", raising=False)
    monkeypatch.delenv("GLIMI_LLM_AGENT_MAP", raising=False)
    assert kr._provider_for("persona", "claude-haiku-4-5") == "claude"


def test_provider_for_capped_no_local(mem_store, monkeypatch):
    monkeypatch.delenv("GLIMI_LLM_BACKEND", raising=False)
    monkeypatch.delenv("GLIMI_LLM_AGENT_MAP", raising=False)
    # Force "over cap" deterministically; no local backend available.
    monkeypatch.setattr(budget, "allow_claude", lambda c: False)
    monkeypatch.setattr(kr, "_backend_available", lambda p: False)
    assert kr._provider_for("persona", "claude-haiku-4-5") == kr.CAPPED


def test_provider_for_capped_to_ollama_when_local(mem_store, monkeypatch):
    monkeypatch.delenv("GLIMI_LLM_BACKEND", raising=False)
    monkeypatch.delenv("GLIMI_LLM_AGENT_MAP", raising=False)
    monkeypatch.setattr(budget, "allow_claude", lambda c: False)
    monkeypatch.setattr(kr, "_backend_available", lambda p: p == "ollama")
    assert kr._provider_for("persona", "claude-haiku-4-5") == "ollama"


def test_provider_for_over_cap_via_seeded_spend(mem_store, monkeypatch):
    """End-to-end: real env + seeded spend (no monkeypatch of allow_claude)."""
    monkeypatch.delenv("GLIMI_LLM_BACKEND", raising=False)
    monkeypatch.delenv("GLIMI_LLM_AGENT_MAP", raising=False)
    monkeypatch.setenv("GLIMI_MONTHLY_CAP_USD", "0.01")
    monkeypatch.setattr(kr, "_backend_available", lambda p: False)  # no local
    mem_store.record_usage(model="claude-opus-4-8", backend="anthropic_sdk",
                           est_cost=1.0, ts=_this_month_ts())
    assert kr._provider_for("persona", "claude-haiku-4-5") == kr.CAPPED


def test_capped_is_not_backend_available():
    assert kr._backend_available(kr.CAPPED) is False


# ── Guard point 2: the facade ─────────────────────────────────────────

class _Sink:
    def __init__(self):
        self.rows = []

    def record_usage(self, **kw):
        self.rows.append(kw)
        return len(self.rows)


@pytest.fixture()
def sink():
    saved = llm._usage_sink
    s = _Sink()
    llm.set_usage_sink(s)
    try:
        yield s
    finally:
        llm.set_usage_sink(saved)


def test_facade_capped_no_local_returns_empty_and_records(sink, monkeypatch):
    """Claude backend selected + over cap + no local → empty capped response,
    was_blocked recorded."""
    monkeypatch.setattr(budget, "allow_claude", lambda c: False)

    # Pretend the selector picked a Claude backend; no ollama available.
    class _FakeClaude:
        name = "anthropic_sdk"

        def generate(self, **kw):
            raise AssertionError("Claude backend must NOT be dispatched over cap")

    monkeypatch.setattr(llm, "_select_backend", lambda **kw: _FakeClaude())
    monkeypatch.setattr(llm, "_get_backend_instance", lambda n: None)  # no ollama

    resp = llm.generate(system="s", user="u", model="claude-haiku-4-5",
                        agent_type="memory_extract")
    assert resp.text == ""
    assert resp.error == "budget_capped"
    assert len(sink.rows) == 1
    assert sink.rows[0]["was_blocked"] is True
    assert sink.rows[0]["backend"] == "capped"
    assert sink.rows[0]["est_cost"] == 0.0


def test_facade_capped_forces_ollama_when_local(monkeypatch):
    """Over cap + local available → dispatch ollama, never Claude."""
    monkeypatch.setattr(budget, "allow_claude", lambda c: False)

    dispatched = {}

    class _FakeClaude:
        name = "claude_cli"

        def generate(self, **kw):
            raise AssertionError("must not dispatch Claude over cap")

    class _FakeOllama:
        name = "ollama"

        def available(self):
            return True

        def generate(self, **kw):
            dispatched["model"] = kw.get("model")
            return LLMResponse(text="local says hi", model=kw.get("model", ""))

    monkeypatch.setattr(llm, "_select_backend", lambda **kw: _FakeClaude())
    monkeypatch.setattr(llm, "_get_backend_instance",
                        lambda n: _FakeOllama() if n == "ollama" else None)

    resp = llm.generate(system="s", user="u", model="claude-haiku-4-5",
                        agent_type="persona")
    assert resp.text == "local says hi"
    assert dispatched  # ollama was the one dispatched


def test_facade_within_cap_dispatches_claude(monkeypatch):
    """Unset/under cap → Claude backend dispatched normally (no regression)."""
    monkeypatch.setattr(budget, "allow_claude", lambda c: True)

    class _FakeClaude:
        name = "anthropic_sdk"

        def generate(self, **kw):
            return LLMResponse(text="claude reply", model=kw.get("model", ""))

    monkeypatch.setattr(llm, "_select_backend", lambda **kw: _FakeClaude())
    resp = llm.generate(system="s", user="u", model="claude-haiku-4-5",
                        agent_type="mgr")
    assert resp.text == "claude reply"


def test_facade_stream_capped_no_local_is_empty(sink, monkeypatch):
    monkeypatch.setattr(budget, "allow_claude", lambda c: False)

    class _FakeClaude:
        name = "anthropic_sdk"

        def stream_lines(self, **kw):
            raise AssertionError("must not stream Claude over cap")

    monkeypatch.setattr(llm, "_select_backend", lambda **kw: _FakeClaude())
    monkeypatch.setattr(llm, "_get_backend_instance", lambda n: None)

    out = list(llm.stream_lines(system="s", user="u", model="claude-haiku-4-5",
                                agent_type="judge"))
    assert out == []
    assert len(sink.rows) == 1
    assert sink.rows[0]["was_blocked"] is True


def test_facade_non_claude_backend_unaffected(sink, monkeypatch):
    """A non-Claude backend (echo) is never diverted, even over cap."""
    monkeypatch.setattr(budget, "allow_claude", lambda c: False)
    resp = llm.generate(system="s", user="hi", model="echo",
                        agent_type="persona", backend="echo")
    assert resp.text  # echo ran normally
    # the recorded row is the real echo row, not a capped row
    assert all(r.get("was_blocked") is not True for r in sink.rows)


# ── was_blocked persistence ───────────────────────────────────────────

def test_was_blocked_persists_in_memory(mem_store):
    mem_store.record_usage(model="m", backend="capped", was_blocked=True,
                           ts=_this_month_ts())
    rows = mem_store._usage
    assert rows[-1]["was_blocked"] == 1


def test_was_blocked_persists_sqlite(tmp_path):
    from community import db
    from community.adapters.kernel_store import SqliteKernelStore
    saved = db.DB_PATH
    db.DB_PATH = str(tmp_path / "community.db")
    db.init_db()
    try:
        s = SqliteKernelStore()
        s.record_usage(model="m", backend="capped", was_blocked=True)
        s.record_usage(model="m", backend="anthropic_sdk", was_blocked=False)
        conn = sqlite3.connect(db.DB_PATH)
        vals = [r[0] for r in conn.execute(
            "SELECT was_blocked FROM usage_records ORDER BY id").fetchall()]
        conn.close()
        assert vals == [1, 0]
    finally:
        db.DB_PATH = saved


def test_was_blocked_column_added_to_pre_feature_db(tmp_path):
    """OLD usage_records without was_blocked → migration adds it (additive)."""
    from community import db
    from community.adapters.kernel_store import SqliteKernelStore
    saved = db.DB_PATH
    path = str(tmp_path / "old.db")
    db.DB_PATH = path
    try:
        db.init_db()
        # simulate a pre-feature usage_records (drop the new column by rebuilding)
        conn = sqlite3.connect(path)
        conn.executescript("""
            DROP TABLE IF EXISTS usage_records;
            CREATE TABLE usage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, community TEXT, agent_id TEXT, agent_type TEXT,
                model TEXT, backend TEXT, input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0,
                cache_write_tokens INTEGER DEFAULT 0, est_cost REAL DEFAULT 0,
                estimated INTEGER DEFAULT 0, latency_ms INTEGER
            );
        """)
        conn.commit()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(usage_records)").fetchall()]
        assert "was_blocked" not in cols
        conn.close()

        db._migrate_schema()

        conn = sqlite3.connect(path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(usage_records)").fetchall()]
        conn.close()
        assert "was_blocked" in cols

        s = SqliteKernelStore()
        assert s.record_usage(model="m", backend="capped", was_blocked=True) >= 1
    finally:
        db.DB_PATH = saved
