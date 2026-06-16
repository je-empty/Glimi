"""SQLite-layer coverage for reactions + replies/threads + migration (Phase 1-2).

Exercises ``src.db`` directly against a throwaway temp DB:
  - log_message returns the new row id (and the existing id on 30s-dedupe)
  - reactions add/remove idempotency + UNIQUE
  - get_reactions / get_reactions_for batch read
  - set_reply / get_thread (thread_root denormalization)
  - get_recent_messages carries reply_to + a folded reactions summary
  - MIGRATION idempotency: init_db twice, and an existing pre-migration DB
    (conversations missing the new columns + no reactions table) upgrades safely
    with NO backfill.

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_reactions_db.py -q
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from src import db


@pytest.fixture()
def fresh_db(tmp_path):
    """Point src.db at a fresh temp DB initialized via init_db()."""
    saved = db.DB_PATH
    path = str(tmp_path / "community.db")
    db.DB_PATH = path
    db.init_db()
    db.save_user({"id": "owner", "name": "오너"})
    db.save_agent_profile({"id": "agent-1", "type": "persona", "name": "소은"})
    try:
        yield path
    finally:
        db.DB_PATH = saved


# ── log_message id return ─────────────────────────────────────────────

def test_log_message_returns_new_row_id(fresh_db):
    mid1 = db.log_message("dm-x", "owner", "안녕")
    mid2 = db.log_message("dm-x", "agent-1", "안녕하세요")
    assert isinstance(mid1, int) and isinstance(mid2, int)
    assert mid2 > mid1


def test_log_message_dedup_returns_existing_id(fresh_db):
    mid1 = db.log_message("dm-x", "owner", "같은말")
    mid2 = db.log_message("dm-x", "owner", "같은말")  # within 30s window → dedup
    assert mid2 == mid1  # existing id, NOT None and NOT a fresh id


def test_log_message_reply_sets_thread_root(fresh_db):
    root = db.log_message("dm-x", "owner", "부모 메시지")
    child = db.log_message("dm-x", "agent-1", "답글", reply_to=root)
    conn = sqlite3.connect(fresh_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT reply_to, thread_root FROM conversations WHERE id=?", (child,)).fetchone()
    conn.close()
    assert row["reply_to"] == root
    assert row["thread_root"] == root  # parent had no thread_root → parent id


def test_reply_to_grandchild_keeps_root(fresh_db):
    root = db.log_message("dm-x", "owner", "root")
    child = db.log_message("dm-x", "agent-1", "child", reply_to=root)
    grand = db.log_message("dm-x", "owner", "grandchild", reply_to=child)
    conn = sqlite3.connect(fresh_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT thread_root FROM conversations WHERE id=?", (grand,)).fetchone()
    conn.close()
    assert row["thread_root"] == root  # denormalized to the original root, not the parent


# ── reactions add/remove idempotency + UNIQUE ─────────────────────────

def test_add_reaction_idempotent(fresh_db):
    mid = db.log_message("dm-x", "agent-1", "hi")
    assert db.add_reaction(mid, "owner", "❤️") is True   # inserted
    assert db.add_reaction(mid, "owner", "❤️") is False  # UNIQUE → ignored
    assert len(db.get_reactions(mid)) == 1


def test_add_reaction_distinct_emoji_and_actor(fresh_db):
    mid = db.log_message("dm-x", "agent-1", "hi")
    assert db.add_reaction(mid, "owner", "❤️") is True
    assert db.add_reaction(mid, "owner", "👍") is True       # different emoji
    assert db.add_reaction(mid, "agent-1", "❤️") is True     # different actor
    assert len(db.get_reactions(mid)) == 3


def test_add_reaction_missing_message_is_noop(fresh_db):
    # FK ON → insert against non-existent message id no-ops (returns False).
    assert db.add_reaction(999999, "owner", "❤️") is False
    assert db.get_reactions(999999) == []


def test_remove_reaction_toggles_off(fresh_db):
    mid = db.log_message("dm-x", "agent-1", "hi")
    db.add_reaction(mid, "owner", "❤️")
    db.remove_reaction(mid, "owner", "❤️")
    assert db.get_reactions(mid) == []
    db.remove_reaction(mid, "owner", "❤️")  # double-remove is safe no-op


def test_get_reactions_for_batch(fresh_db):
    m1 = db.log_message("dm-x", "agent-1", "a")
    m2 = db.log_message("dm-x", "agent-1", "b")
    m3 = db.log_message("dm-x", "agent-1", "c")  # no reactions
    db.add_reaction(m1, "owner", "❤️")
    db.add_reaction(m1, "agent-1", "👍")
    db.add_reaction(m2, "owner", "🔥")
    got = db.get_reactions_for([m1, m2, m3])
    assert set(got.keys()) == {m1, m2}  # m3 absent (no reactions)
    assert {r["emoji"] for r in got[m1]} == {"❤️", "👍"}
    assert got[m2][0]["emoji"] == "🔥"


def test_get_reactions_for_empty(fresh_db):
    assert db.get_reactions_for([]) == {}


def test_reactions_cascade_on_message_delete(fresh_db):
    mid = db.log_message("dm-x", "agent-1", "hi")
    db.add_reaction(mid, "owner", "❤️")
    conn = db.get_conn()
    conn.execute("DELETE FROM conversations WHERE id=?", (mid,))
    conn.commit()
    conn.close()
    assert db.get_reactions(mid) == []  # cascaded


# ── set_reply / get_thread ────────────────────────────────────────────

def test_set_reply_and_get_thread(fresh_db):
    root = db.log_message("dm-x", "owner", "root msg")
    c1 = db.log_message("dm-x", "agent-1", "reply 1", reply_to=root)
    # a standalone message later marked as a reply via set_reply
    c2 = db.log_message("dm-x", "owner", "reply 2")
    db.set_reply(c2, root)
    thread = db.get_thread(root)
    ids = [m["id"] for m in thread]
    assert ids == sorted([root, c1, c2])  # id ASC, includes root + replies


def test_get_thread_unknown_root_empty(fresh_db):
    assert db.get_thread(424242) == []


# ── get_recent_messages enrichment ────────────────────────────────────

def test_get_recent_messages_carries_reply_to_and_reactions(fresh_db):
    root = db.log_message("dm-x", "owner", "부모")
    child = db.log_message("dm-x", "agent-1", "답글", reply_to=root)
    db.add_reaction(child, "owner", "❤️")
    db.add_reaction(child, "owner", "👍")
    db.add_reaction(root, "agent-1", "🔥")
    rows = db.get_recent_messages("dm-x")
    by_id = {r["id"]: r for r in rows}
    # reply_to flows through
    assert by_id[child]["reply_to"] == root
    assert by_id[root]["reply_to"] is None
    # reactions summary folded in: [{emoji, count, actors}]
    child_react = {r["emoji"]: r for r in by_id[child]["reactions"]}
    assert child_react["❤️"]["count"] == 1
    assert child_react["👍"]["actors"] == ["owner"]
    assert by_id[root]["reactions"][0]["emoji"] == "🔥"


def test_get_recent_messages_no_reactions_empty_list(fresh_db):
    db.log_message("dm-x", "owner", "plain")
    rows = db.get_recent_messages("dm-x")
    assert rows[0]["reactions"] == []


# ── migration idempotency ─────────────────────────────────────────────

def test_init_db_twice_is_idempotent(fresh_db):
    # Already init'd once by the fixture; a second call must not raise.
    db.init_db()
    db.init_db()
    # reactions table + new columns still present and functional.
    mid = db.log_message("dm-x", "agent-1", "post-reinit")
    assert db.add_reaction(mid, "owner", "❤️") is True


def test_migration_upgrades_pre_migration_db(tmp_path):
    """Simulate an OLD community DB: conversations WITHOUT reply_to/thread_root/
    platform_message_id and NO reactions table. _migrate_schema must add them
    with NO backfill, and existing rows stay intact.

    Build a complete current DB via init_db(), then rewind ONLY the
    conversations table (recreate without the new columns) and drop the
    reactions table — a faithful "pre-this-feature" snapshot — and re-migrate.
    """
    saved = db.DB_PATH
    path = str(tmp_path / "old.db")
    db.DB_PATH = path
    try:
        db.init_db()  # full, current schema

        # Rewind to a pre-feature state: drop reactions table + rebuild
        # conversations without reply_to/thread_root/platform_message_id.
        conn = sqlite3.connect(path)
        conn.executescript("""
            DROP TABLE IF EXISTS reactions;
            DROP INDEX IF EXISTS idx_conv_thread;
            DROP TABLE IF EXISTS conversations;
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                speaker TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                context_emotion TEXT
            );
        """)
        conn.execute("INSERT INTO conversations (channel, speaker, message) VALUES (?,?,?)",
                     ("dm-x", "owner", "legacy msg"))
        conn.commit()
        # confirm legacy state: no reply_to column, no reactions table
        cols = [r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        assert "reply_to" not in cols
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "reactions" not in tables
        conn.close()

        # Run the migration.
        db._migrate_schema()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        assert "reply_to" in cols and "thread_root" in cols and "platform_message_id" in cols
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "reactions" in tables
        # NO backfill: the legacy row's new columns are NULL.
        row = conn.execute("SELECT reply_to, thread_root FROM conversations WHERE message='legacy msg'").fetchone()
        assert row["reply_to"] is None and row["thread_root"] is None
        conn.close()

        # Migration is idempotent — second run no-ops.
        db._migrate_schema()

        # And the upgraded DB is now fully functional.
        mid = db.log_message("dm-x", "agent-1", "after migrate")
        assert db.add_reaction(mid, "owner", "❤️") is True
        rows = db.get_recent_messages("dm-x")
        assert all("reactions" in r for r in rows)
    finally:
        db.DB_PATH = saved
