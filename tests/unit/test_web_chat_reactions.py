"""End-to-end web-chat reactions + replies/threads tests — phase 4 wiring.

Builds on the same throwaway-community + admin-session scaffold as
``test_web_chat_seam`` (an isolated GLIMI_DATA_DIR, a community whose backend is
configured to ECHO via its ``.env`` so a real turn round-trips, and a signed
admin cookie). Exercises the REAL transport:

  - WS ``add_reaction`` → persisted in the ``reactions`` table + broadcast a
    ``reaction`` frame + fires ``memory.record_reaction_signal`` exactly once;
  - WS ``remove_reaction`` → toggle-off, count drops, ``reaction_removed`` frame;
  - a ``text`` frame with ``reply_to`` → the reply pointer persists and the
    history endpoint returns it as a resolved ``reply_to`` context;
  - WS ``fetch_thread`` → a ``thread`` frame with root + replies;
  - the history endpoint folds ``reactions`` into each row.

CI without httpx/websockets installed skips via importorskip.
"""
import itertools
import shutil
import tempfile

import pytest

_USER_SEQ = itertools.count(5000)

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("websockets")

from starlette.testclient import TestClient


@pytest.fixture()
def seeded_app(monkeypatch):
    """Isolated platform data dir + a throwaway echo-configured community + an
    admin session cookie. Yields (client, cid). Mirrors test_web_chat_seam."""
    data_dir = tempfile.mkdtemp(prefix="glimi-webreact-test-")
    monkeypatch.setenv("GLIMI_DATA_DIR", data_dir)
    monkeypatch.setenv("GLIMI_LANG", "ko")
    monkeypatch.delenv("GLIMI_LLM_BACKEND", raising=False)
    monkeypatch.delenv("GLIMI_LLM_AGENT_MAP", raising=False)

    n = next(_USER_SEQ)
    cid = f"wsreact{n}"
    from src import community as comm
    cdir = comm.COMMUNITIES_DIR / cid
    community_preexisted = cdir.exists()
    (cdir / "logs").mkdir(parents=True, exist_ok=True)
    (cdir / ".env").write_text("GLIMI_LLM_BACKEND=echo\n", encoding="utf-8")

    monkeypatch.setenv("GLIMI_COMMUNITY", cid)
    comm.set_community(cid)
    import src.db as db
    db.DB_PATH = None
    db.init_db()
    db.save_agent_profile({"id": "mgr", "type": "mgr", "name": "유나"})
    db.save_agent_profile({"id": "agent-persona-001", "type": "persona", "name": "소은"})
    db.save_user({"id": "owner", "name": "오너"})
    db.set_channel_participants("group-cafe", ["mgr", "agent-persona-001"])
    # Seed a DM history: an owner turn + an agent turn (each gets a real id).
    db.log_message("dm-agent-persona-001", "owner", "안녕 소은")
    db.log_message("dm-agent-persona-001", "agent-persona-001", "안녕하세요!")

    from src.platform import accounts, sessions
    from src.platform.config import SESSION_COOKIE_NAME
    uid = accounts.create_account(f"wsreact{n}", "pw-12345", role="admin")
    token = sessions.sign_session(uid)

    from src.platform.app import app
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    try:
        yield client, cid
    finally:
        if not community_preexisted:
            shutil.rmtree(cdir, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def _scoped(cid):
    """Context-managed community scope for direct DB assertions in-test."""
    from src.platform.community_ctx import run_in_community
    return run_in_community


def _latest_msg_id(cid, channel, speaker, text):
    """Resolve the row id of a seeded/known message for reaction targeting."""
    from src.platform.community_ctx import run_in_community

    def _q():
        from src import db
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT id FROM conversations WHERE channel=? AND speaker=? AND message=? "
                "ORDER BY id DESC LIMIT 1",
                (channel, speaker, text),
            ).fetchone()
        finally:
            conn.close()
        return row["id"] if row else None

    return run_in_community(cid, _q)


def _drain_for(ws, ftype, max_frames=12):
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame.get("type") == ftype:
            return frame
    return None


def _drain_text(ws, max_frames=12):
    return _drain_for(ws, "text", max_frames)


# ── add_reaction ────────────────────────────────────────────────────────

def test_ws_add_reaction_persists_broadcasts_and_signals_once(seeded_app, monkeypatch):
    """add_reaction → row persisted + a 'reaction' frame broadcast + the
    relational signal fires EXACTLY once (idempotent re-add does not re-fire)."""
    client, cid = seeded_app
    target = _latest_msg_id(cid, "dm-agent-persona-001", "agent-persona-001", "안녕하세요!")
    assert target is not None

    # Count record_reaction_signal invocations.
    from glimi import memory
    calls = {"n": 0}
    real = memory.record_reaction_signal

    def _spy(agent_id, actor_id, emoji, reaction_id=None):
        calls["n"] += 1
        return real(agent_id, actor_id, emoji, reaction_id)

    monkeypatch.setattr(memory, "record_reaction_signal", _spy)

    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        # First register on the channel (a ping joins the room for broadcasts).
        ws.send_json({"type": "ping", "channel": "dm-agent-persona-001"})
        assert ws.receive_json()["type"] == "pong"

        ws.send_json({
            "type": "add_reaction", "channel": "dm-agent-persona-001",
            "id": target, "emoji": "❤️",
        })
        frame = _drain_for(ws, "reaction")
        assert frame is not None, "no reaction frame broadcast"
        assert frame["id"] == target
        assert frame["emoji"] == "❤️"
        assert frame["count"] == 1
        assert frame["actor_id"] == "owner"

        # Idempotent re-add: still broadcasts (count unchanged), but no 2nd signal.
        ws.send_json({
            "type": "add_reaction", "channel": "dm-agent-persona-001",
            "id": target, "emoji": "❤️",
        })
        frame2 = _drain_for(ws, "reaction")
        assert frame2 is not None
        assert frame2["count"] == 1  # UNIQUE → still one

    # Persisted in the reactions table.
    from src.platform.community_ctx import run_in_community

    def _reacts():
        from src import db
        return db.get_reactions(target)

    reacts = run_in_community(cid, _reacts)
    assert any(r["emoji"] == "❤️" and r["actor_id"] == "owner" for r in reacts)
    # The relational signal fired exactly once (real insert only).
    assert calls["n"] == 1


def test_ws_add_reaction_rejects_cross_channel(seeded_app):
    """A reaction whose target message lives in a DIFFERENT channel is rejected."""
    client, cid = seeded_app
    # This message is in dm-agent-persona-001 …
    target = _latest_msg_id(cid, "dm-agent-persona-001", "owner", "안녕 소은")
    assert target is not None
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        # … but we react FROM a different (also user-postable) channel.
        ws.send_json({
            "type": "add_reaction", "channel": "dm-mgr",
            "id": target, "emoji": "❤️",
        })
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert "not in channel" in frame["error"]


def test_ws_reaction_rejects_internal_channel(seeded_app):
    client, cid = seeded_app
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({
            "type": "add_reaction", "channel": "mgr-system-log",
            "id": 1, "emoji": "❤️",
        })
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert "not user-postable" in frame["error"]


# ── remove_reaction ─────────────────────────────────────────────────────

def test_ws_remove_reaction_toggles_off(seeded_app):
    client, cid = seeded_app
    target = _latest_msg_id(cid, "dm-agent-persona-001", "agent-persona-001", "안녕하세요!")
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({"type": "ping", "channel": "dm-agent-persona-001"})
        ws.receive_json()
        ws.send_json({"type": "add_reaction", "channel": "dm-agent-persona-001",
                      "id": target, "emoji": "👍"})
        added = _drain_for(ws, "reaction")
        assert added["count"] == 1
        ws.send_json({"type": "remove_reaction", "channel": "dm-agent-persona-001",
                      "id": target, "emoji": "👍"})
        removed = _drain_for(ws, "reaction_removed")
        assert removed is not None
        assert removed["count"] == 0
        assert removed["emoji"] == "👍"

    from src.platform.community_ctx import run_in_community

    def _reacts():
        from src import db
        return db.get_reactions(target)

    assert run_in_community(cid, _reacts) == []


# ── reply_to persistence + history ──────────────────────────────────────

def test_ws_reply_to_persists_and_history_returns_it(seeded_app):
    """A text turn carrying reply_to → the human turn's row gets the reply pointer
    backfilled, and /chat/history returns a resolved reply_to context."""
    client, cid = seeded_app
    parent = _latest_msg_id(cid, "dm-agent-persona-001", "agent-persona-001", "안녕하세요!")
    assert parent is not None

    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({
            "type": "text", "channel": "dm-agent-persona-001",
            "agent": "agent-persona-001", "text": "이건 답장이야", "reply_to": parent,
        })
        # Drain the agent's echo reply (proves the turn completed).
        assert _drain_text(ws) is not None

    r = client.get(f"/community/{cid}/chat/history?channel=dm-agent-persona-001&limit=50")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    by_text = {m["text"]: m for m in msgs}
    reply_row = by_text.get("이건 답장이야")
    assert reply_row is not None, "the reply turn was not persisted"
    rt = reply_row.get("reply_to")
    assert rt is not None, "reply_to was not persisted/returned"
    assert rt["id"] == parent
    # Parent is in-window → resolved author + preview.
    assert rt["author"] == "소은"
    assert "안녕하세요" in (rt["preview"] or "")


def test_ws_reply_to_other_channel_dropped(seeded_app):
    """A reply pointer to a message in another channel is silently dropped (the
    turn still runs, but the human row carries no cross-channel reply_to)."""
    client, cid = seeded_app
    # parent lives in dm-agent-persona-001; we reply in dm-mgr.
    parent = _latest_msg_id(cid, "dm-agent-persona-001", "owner", "안녕 소은")
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({
            "type": "text", "channel": "dm-mgr", "agent": "mgr",
            "text": "교차채널 답장", "reply_to": parent,
        })
        assert _drain_text(ws) is not None

    r = client.get(f"/community/{cid}/chat/history?channel=dm-mgr&limit=50")
    msgs = r.json()["messages"]
    by_text = {m["text"]: m for m in msgs}
    row = by_text.get("교차채널 답장")
    assert row is not None
    assert row.get("reply_to") is None


# ── fetch_thread ────────────────────────────────────────────────────────

def test_ws_fetch_thread_returns_root_and_replies(seeded_app):
    """fetch_thread on a root id returns the root + its reply chain, id ASC."""
    client, cid = seeded_app
    root = _latest_msg_id(cid, "dm-agent-persona-001", "agent-persona-001", "안녕하세요!")
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        # Make a reply so the thread has >1 message.
        ws.send_json({
            "type": "text", "channel": "dm-agent-persona-001",
            "agent": "agent-persona-001", "text": "스레드 답글", "reply_to": root,
        })
        assert _drain_text(ws) is not None

        ws.send_json({
            "type": "fetch_thread", "channel": "dm-agent-persona-001", "root": root,
        })
        frame = _drain_for(ws, "thread")
        assert frame is not None
        assert frame["root"] == root
        msgs = frame["messages"]
        texts = [m["text"] for m in msgs]
        # Root first (id ASC), then the reply.
        assert "안녕하세요!" in texts
        assert "스레드 답글" in texts
        assert texts.index("안녕하세요!") < texts.index("스레드 답글")
        # Rows are display-resolved.
        root_row = next(m for m in msgs if m["text"] == "안녕하세요!")
        assert root_row["display_name"] == "소은"
        assert root_row["is_user"] is False


def test_ws_fetch_thread_missing_root_is_empty(seeded_app):
    client, cid = seeded_app
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({
            "type": "fetch_thread", "channel": "dm-agent-persona-001", "root": 999999,
        })
        frame = _drain_for(ws, "thread")
        assert frame is not None
        assert frame["messages"] == []


# ── history includes reactions ──────────────────────────────────────────

def test_history_includes_reactions(seeded_app):
    """A reacted message's history row carries the reaction summary."""
    client, cid = seeded_app
    target = _latest_msg_id(cid, "dm-agent-persona-001", "agent-persona-001", "안녕하세요!")
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({"type": "ping", "channel": "dm-agent-persona-001"})
        ws.receive_json()
        ws.send_json({"type": "add_reaction", "channel": "dm-agent-persona-001",
                      "id": target, "emoji": "❤️"})
        assert _drain_for(ws, "reaction") is not None

    r = client.get(f"/community/{cid}/chat/history?channel=dm-agent-persona-001&limit=50")
    msgs = r.json()["messages"]
    by_id = {m["id"]: m for m in msgs}
    row = by_id.get(target)
    assert row is not None
    reacts = row.get("reactions") or []
    assert any(rr["emoji"] == "❤️" and rr["count"] == 1 for rr in reacts)
    assert "owner" in reacts[0]["actors"]
