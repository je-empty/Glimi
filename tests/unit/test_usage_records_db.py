"""usage_records 테이블 + pricing + 토큰 추정 + 마이그레이션 멱등성.

검증:
  - SqliteKernelStore.record_usage / usage_spend / usage_by_agent roundtrip + 집계
  - since 필터 (월/일 경계), estimated_count, avg_latency
  - ts 는 UTC-aware ISO
  - glimi.llm.pricing.estimate_cost: SDK 정확값 · 캐시 요율 · local=$0 · 미지 모델=$0
  - chars/4 추정은 estimated 로 표시 (절대 정확 값으로 위장 안 함)
  - init_db 두 번 멱등 + pre-feature DB (usage_records 부재) 가 백필 없이 안전 업그레이드

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_usage_records_db.py -q
"""
from __future__ import annotations

import sqlite3

import pytest

from community import db
from community.adapters.kernel_store import SqliteKernelStore
from glimi.llm import pricing


@pytest.fixture()
def store(tmp_path):
    saved = db.DB_PATH
    db.DB_PATH = str(tmp_path / "community.db")
    db.init_db()
    try:
        yield SqliteKernelStore()
    finally:
        db.DB_PATH = saved


# ── record / aggregate roundtrip ──────────────────────────────────────

def test_record_and_spend_roundtrip(store):
    uid = store.record_usage(
        agent_id="agent-1", agent_type="memory_extract",
        model="claude-haiku-4-5", backend="anthropic_sdk",
        input_tokens=1000, output_tokens=200, est_cost=0.002,
        estimated=False, latency_ms=300,
    )
    assert uid >= 1
    sp = store.usage_spend()
    assert sp["call_count"] == 1
    assert sp["input_tokens"] == 1000
    assert sp["output_tokens"] == 200
    assert abs(sp["total_cost"] - 0.002) < 1e-9
    assert sp["estimated_count"] == 0
    assert sp["avg_latency_ms"] == 300


def test_estimated_count_tracks_cli_rows(store):
    store.record_usage(model="claude-haiku-4-5", backend="anthropic_sdk",
                       input_tokens=100, output_tokens=10, est_cost=0.001,
                       estimated=False, latency_ms=200)
    store.record_usage(model="claude-haiku-4-5", backend="claude_cli",
                       input_tokens=50, output_tokens=5, est_cost=0.0005,
                       estimated=True, latency_ms=800)
    sp = store.usage_spend()
    assert sp["call_count"] == 2
    assert sp["estimated_count"] == 1  # only the CLI row is estimated


def test_ts_is_utc_aware_iso(store):
    store.record_usage(model="claude-haiku-4-5", backend="anthropic_sdk")
    conn = sqlite3.connect(db.DB_PATH)
    ts = conn.execute("SELECT ts FROM usage_records").fetchone()[0]
    conn.close()
    assert ts.endswith("+00:00")


def test_explicit_ts_respected_and_since_filter(store):
    store.record_usage(model="claude-opus-4-8", backend="anthropic_sdk",
                       est_cost=1.0, ts="2020-01-01T00:00:00+00:00")
    store.record_usage(model="claude-opus-4-8", backend="anthropic_sdk",
                       est_cost=2.0, ts="2030-01-01T00:00:00+00:00")
    # Only the 2030 row counts when filtering since 2025.
    sp = store.usage_spend(since="2025-01-01T00:00:00+00:00")
    assert sp["call_count"] == 1
    assert abs(sp["total_cost"] - 2.0) < 1e-9
    # Both count with no filter.
    assert store.usage_spend()["call_count"] == 2


def test_usage_by_agent_groups(store):
    store.record_usage(agent_id="a", agent_type="persona", model="m", backend="b",
                       est_cost=0.5, input_tokens=10)
    store.record_usage(agent_id="a", agent_type="persona", model="m", backend="b",
                       est_cost=0.5, input_tokens=10)
    store.record_usage(agent_id="b", agent_type="mgr", model="m", backend="b",
                       est_cost=0.1, input_tokens=5)
    rows = store.usage_by_agent()
    by = {r["agent_id"]: r for r in rows}
    assert abs(by["a"]["total_cost"] - 1.0) < 1e-9
    assert by["a"]["call_count"] == 2
    assert by["a"]["input_tokens"] == 20
    # Ordered by total_cost DESC → agent 'a' first.
    assert rows[0]["agent_id"] == "a"


def test_empty_spend_is_zeroed(store):
    sp = store.usage_spend()
    assert sp["total_cost"] == 0.0
    assert sp["call_count"] == 0
    assert sp["avg_latency_ms"] == 0


# ── pricing ───────────────────────────────────────────────────────────

def test_pricing_sdk_exact():
    # opus 4.8: $5/1M in, $25/1M out.
    cost = pricing.estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000)
    assert abs(cost - (5.0 + 25.0)) < 1e-9


def test_pricing_cache_rates():
    # cache_read = 0.1x input, cache_write = 1.25x input.
    cost = pricing.estimate_cost("claude-opus-4-8", 0, 0,
                                 cache_read_tokens=1_000_000,
                                 cache_write_tokens=1_000_000)
    assert abs(cost - (5.0 * 0.1 + 5.0 * 1.25)) < 1e-9


def test_pricing_local_and_unknown_are_free():
    assert pricing.estimate_cost("ollama:local", 1_000_000, 1_000_000) == 0.0
    assert pricing.estimate_cost("gpt-4-turbo", 1_000_000, 1_000_000) == 0.0
    assert pricing.estimate_cost("echo", 999, 999) == 0.0


def test_pricing_is_priced_flag():
    assert pricing.is_priced("claude-opus-4-8") is True
    assert pricing.is_priced("ollama:local") is False
    assert pricing.is_priced(None) is False


def test_pricing_as_of_present():
    assert isinstance(pricing.PRICING_AS_OF, str) and pricing.PRICING_AS_OF


def test_opus_4_8_priced_after_alias_reconcile():
    """Regression: runtime uses claude-opus-4-8; pricing must NOT silently $0 it."""
    from glimi.llm.anthropic_sdk import _resolve_model
    resolved = _resolve_model("claude-opus-4-8")
    assert resolved == "claude-opus-4-8"
    assert pricing.estimate_cost(resolved, 1000, 0) > 0


# ── chars/4 estimation (honest labeling) ──────────────────────────────

def test_chars_over_4_estimation():
    assert pricing.estimate_tokens_from_chars("x" * 400) == 100
    assert pricing.estimate_tokens_from_chars("") == 0
    assert pricing.estimate_tokens_from_chars(None) == 0


def test_estimated_row_is_flagged_estimated(store):
    """A CLI-estimated row records estimated=1 — never presented as exact."""
    in_tok = pricing.estimate_tokens_from_chars("a" * 800)  # 200
    store.record_usage(model="claude-haiku-4-5", backend="claude_cli",
                       input_tokens=in_tok, output_tokens=0,
                       est_cost=pricing.estimate_cost("claude-haiku-4-5", in_tok, 0),
                       estimated=True)
    conn = sqlite3.connect(db.DB_PATH)
    estimated = conn.execute("SELECT estimated FROM usage_records").fetchone()[0]
    conn.close()
    assert estimated == 1


# ── migration idempotency ─────────────────────────────────────────────

def test_init_db_twice_is_idempotent(store):
    db.init_db()
    db.init_db()
    assert store.record_usage(model="m", backend="b") >= 1


def test_migration_upgrades_pre_feature_db(tmp_path):
    """OLD DB WITHOUT usage_records → _migrate_schema creates it, no backfill."""
    saved = db.DB_PATH
    path = str(tmp_path / "old.db")
    db.DB_PATH = path
    try:
        db.init_db()
        conn = sqlite3.connect(path)
        conn.executescript("""
            DROP INDEX IF EXISTS idx_usage_ts;
            DROP INDEX IF EXISTS idx_usage_community;
            DROP INDEX IF EXISTS idx_usage_agent;
            DROP TABLE IF EXISTS usage_records;
        """)
        conn.commit()
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "usage_records" not in tables
        conn.close()

        db._migrate_schema()

        conn = sqlite3.connect(path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "usage_records" in tables
        conn.close()

        db._migrate_schema()  # idempotent

        s = SqliteKernelStore()
        assert s.record_usage(model="m", backend="b", est_cost=0.01) >= 1
        assert s.usage_spend()["call_count"] == 1
    finally:
        db.DB_PATH = saved
