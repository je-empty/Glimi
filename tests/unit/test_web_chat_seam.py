"""End-to-end web-chat seam test — WebSocket echo round-trip + internal reject.

Exercises the real FastAPI app (src.platform.app:app) over the Starlette/FastAPI
TestClient WebSocket transport, with the ECHO backend so there is no LLM/network
cost. A throwaway community is seeded (one ``mgr`` agent) and a real admin
session cookie is minted so the connect-time auth gate is satisfied for real.

CI without httpx/websockets installed will skip via importorskip.
"""
import itertools
import os
import shutil
import tempfile

import pytest

_USER_SEQ = itertools.count()

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("websockets")

from starlette.testclient import TestClient


@pytest.fixture()
def seeded_app(monkeypatch):
    """Isolated platform data dir + a throwaway community with one mgr agent,
    plus an admin session cookie. Yields (client, cookies, community_id)."""
    data_dir = tempfile.mkdtemp(prefix="glimi-webchat-test-")
    monkeypatch.setenv("GLIMI_DATA_DIR", data_dir)
    monkeypatch.setenv("GLIMI_LLM_BACKEND", "echo")
    monkeypatch.setenv("GLIMI_LANG", "ko")

    cid = "wschat"
    from src import community as comm
    cdir = comm.COMMUNITIES_DIR / cid
    community_preexisted = cdir.exists()
    (cdir / "logs").mkdir(parents=True, exist_ok=True)

    # Scope + init the community DB and seed one mgr agent.
    monkeypatch.setenv("GLIMI_COMMUNITY", cid)
    comm.set_community(cid)
    import src.db as db
    db.DB_PATH = None
    db.init_db()
    db.save_agent_profile({"id": "mgr", "type": "mgr", "name": "유나"})

    # Platform account DB lives under GLIMI_DATA_DIR — create an admin (admin role
    # grants access to all communities) and mint a signed session cookie.
    # NOTE: the platform DB path + secret key are resolved at config import time
    # from GLIMI_DATA_DIR, so they are effectively fixed for the test session.
    # Use a unique username per fixture instance to avoid UNIQUE collisions; the
    # signed session stays consistent because the same secret key is reused.
    from src.platform import accounts, sessions
    from src.platform.config import SESSION_COOKIE_NAME
    uid = accounts.create_account(f"wstester{next(_USER_SEQ)}", "pw-12345", role="admin")
    token = sessions.sign_session(uid)

    # Import the app AFTER env is set so config/secret-key resolve under data_dir.
    from src.platform.app import app

    # Authenticated client (cookie on the instance — avoids per-request cookie
    # deprecation) + a bare unauthenticated client for the auth-reject test.
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, token)
    anon = TestClient(app)
    try:
        yield client, anon, cid
    finally:
        if not community_preexisted:
            shutil.rmtree(cdir, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def _drain_until_text(ws, max_frames=10):
    """Pull frames until a 'text' frame arrives (skip typing/etc.) or give up."""
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame.get("type") == "text":
            return frame
    return None


def test_ws_echo_round_trip(seeded_app):
    client, _anon, cid = seeded_app
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({
            "type": "text",
            "channel": "dm-mgr",   # user-postable
            "agent": "mgr",
            "text": "hello from web",
        })
        frame = _drain_until_text(ws)
        assert frame is not None, "no text frame received from echo backend"
        assert frame["type"] == "text"
        assert frame["channel"] == "dm-mgr"
        assert frame["agent_id"] == "mgr"
        # echo backend echoes the user message back into the reply.
        assert "hello from web" in frame["text"]


def test_ws_internal_channel_rejected(seeded_app):
    client, _anon, cid = seeded_app
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({
            "type": "text",
            "channel": "mgr-system-log",   # NOT user-postable
            "agent": "mgr",
            "text": "should be rejected",
        })
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert "not user-postable" in frame["error"]


def test_ws_rejects_unauthenticated(seeded_app):
    _client, anon, cid = seeded_app
    # No session cookie → connect-time auth fails → socket closed (1008) before
    # any frame can be exchanged.
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with anon.websocket_connect(f"/community/{cid}/chat/ws") as ws:
            ws.send_json({"type": "text", "channel": "dm-mgr", "agent": "mgr", "text": "hi"})
            ws.receive_json()
