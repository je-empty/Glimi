"""End-to-end web-chat seam tests — Phase 2.

Exercises the real FastAPI app (community.platform.app:app) over the Starlette/FastAPI
TestClient WS + REST transports. A throwaway community is seeded (mgr + persona
agents, a group channel, and a couple of conversation rows) and a real admin
session cookie is minted so the connect-time auth gate is satisfied for real.

The dispatcher is CONFIG-DRIVEN (Phase 2): it does NOT force a backend. Tests
that need echo configure it the REAL way — a ``GLIMI_LLM_BACKEND=echo`` line in
the community's ``communities/{cid}/.env`` (config-layering), NOT a hardcoded env
in the handler. This proves the handler no longer forces echo: the only thing
that makes the reply echo is the community config the adapter loads.

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
    """Isolated platform data dir + a throwaway community, plus an admin session
    cookie. Yields (client, anon, community_id).

    The community's backend is configured to ECHO the REAL way — a
    ``GLIMI_LLM_BACKEND=echo`` line in ``communities/{cid}/.env`` — NOT a process
    env force. We deliberately do NOT set ``GLIMI_LLM_BACKEND`` in the process
    env, so the only thing that routes a turn to echo is the community config the
    dispatcher loads. (If the dispatcher still forced echo on its own, this would
    pass trivially; combined with ``test_dispatcher_is_config_driven`` — which
    asserts no echo *without* the .env — it proves config-drive.)

    Seeds: mgr + persona agents, a registered group channel, and a couple of
    conversation rows for history.
    """
    data_dir = tempfile.mkdtemp(prefix="glimi-webchat-test-")
    monkeypatch.setenv("GLIMI_DATA_DIR", data_dir)
    monkeypatch.setenv("GLIMI_LANG", "ko")
    # Make sure no inherited process-env backend masks the config-layering path.
    monkeypatch.delenv("GLIMI_LLM_BACKEND", raising=False)
    monkeypatch.delenv("GLIMI_LLM_AGENT_MAP", raising=False)

    # Unique community per test → fresh DB, no cross-test bleed (the WS turn
    # persists agent replies, which would otherwise leak into later tests).
    n = next(_USER_SEQ)
    cid = f"wschat{n}"
    from community import community as comm
    cdir = comm.COMMUNITIES_DIR / cid
    community_preexisted = cdir.exists()
    (cdir / "logs").mkdir(parents=True, exist_ok=True)
    # Config-layering: configure THIS community's backend = echo via its .env.
    (cdir / ".env").write_text("GLIMI_LLM_BACKEND=echo\n", encoding="utf-8")

    # Scope + init the community DB and seed agents + a group channel + history.
    monkeypatch.setenv("GLIMI_COMMUNITY", cid)
    comm.set_community(cid)
    import community.db as db
    db.DB_PATH = None
    db.init_db()
    db.save_agent_profile({"id": "mgr", "type": "mgr", "name": "유나"})
    db.save_agent_profile({"id": "agent-persona-001", "type": "persona", "name": "소은"})
    # The owner row so history's is_user flag resolves the human turn.
    db.save_user({"id": "owner", "name": "오너"})
    # A registered, user-postable group channel (mgr + persona).
    db.set_channel_participants("group-cafe", ["mgr", "agent-persona-001"])
    # A registered internal channel — must NOT show up in the postable list.
    db.set_channel_participants("internal-group-backchannel", ["mgr", "agent-persona-001"])
    # Seed history for the persona DM channel (owner + agent turns).
    db.log_message("dm-agent-persona-001", "owner", "안녕 소은")
    db.log_message("dm-agent-persona-001", "agent-persona-001", "안녕하세요!")

    # Platform account DB lives under GLIMI_DATA_DIR — create an admin (admin role
    # grants access to all communities) and mint a signed session cookie.
    # NOTE: the platform DB path + secret key are resolved at config import time
    # from GLIMI_DATA_DIR, so they are effectively fixed for the test session.
    # Use a unique username per fixture instance to avoid UNIQUE collisions; the
    # signed session stays consistent because the same secret key is reused.
    from community.platform import accounts, sessions
    from community.platform.config import SESSION_COOKIE_NAME
    uid = accounts.create_account(f"wstester{n}", "pw-12345", role="admin")
    token = sessions.sign_session(uid)

    # Import the app AFTER env is set so config/secret-key resolve under data_dir.
    from community.platform.app import app

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
    """A real turn flows back over WS using the community's CONFIGURED backend.

    Echo is set via the community ``.env`` (config-layering), NOT a process env or
    a handler force — so a successful echo round-trip proves the dispatcher loads
    and honors the configured backend.
    """
    client, _anon, cid = seeded_app
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({
            "type": "text",
            "channel": "dm-mgr",   # user-postable
            "agent": "mgr",
            "text": "hello from web",
        })
        frame = _drain_until_text(ws)
        assert frame is not None, "no text frame received from configured backend"
        assert frame["type"] == "text"
        assert frame["channel"] == "dm-mgr"
        assert frame["agent_id"] == "mgr"
        # echo backend (configured via community .env) echoes the user message.
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


# ── History cold-load endpoint ──────────────────────────────────────────

def test_history_returns_seeded_messages(seeded_app):
    client, _anon, cid = seeded_app
    r = client.get(f"/community/{cid}/chat/history?channel=dm-agent-persona-001&limit=50")
    assert r.status_code == 200
    body = r.json()
    assert body["channel"] == "dm-agent-persona-001"
    msgs = body["messages"]
    # Newest-last (ASC): owner turn first, then the agent reply.
    texts = [m["text"] for m in msgs]
    assert "안녕 소은" in texts
    assert "안녕하세요!" in texts
    assert texts.index("안녕 소은") < texts.index("안녕하세요!")
    # is_user distinguishes the human turn from the agent turn.
    by_text = {m["text"]: m for m in msgs}
    assert by_text["안녕 소은"]["is_user"] is True
    assert by_text["안녕하세요!"]["is_user"] is False
    assert by_text["안녕하세요!"]["speaker_id"] == "agent-persona-001"


def test_history_community_scoped_empty_for_unknown_channel(seeded_app):
    client, _anon, cid = seeded_app
    # A user-postable channel with no rows → empty (community-scoped read).
    r = client.get(f"/community/{cid}/chat/history?channel=dm-mgr&limit=50")
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_history_rejects_system_channel(seeded_app):
    # The genuine system/log channel (the runtime <tools> log) stays hidden — even
    # for READING. Everything else (dm/group/internal) is readable.
    client, _anon, cid = seeded_app
    r = client.get(f"/community/{cid}/chat/history?channel=mgr-system-log")
    assert r.status_code == 400
    assert "not readable" in r.json()["error"]


def test_history_allows_reading_internal_channel(seeded_app):
    # The owner WATCHES the agent-to-agent backchannels ("Behind the scenes"):
    # READING an internal-* channel is allowed (200), even though POSTING is not.
    client, _anon, cid = seeded_app
    r = client.get(
        f"/community/{cid}/chat/history?channel=internal-group-backchannel&limit=50")
    assert r.status_code == 200
    assert r.json()["channel"] == "internal-group-backchannel"
    # No rows seeded for it → empty, but the read itself is permitted (not a 400).
    assert r.json()["messages"] == []


def test_history_requires_auth(seeded_app):
    _client, anon, cid = seeded_app
    r = anon.get(f"/community/{cid}/chat/history?channel=dm-mgr")
    # require_user → 401/403 (redirect disabled for API). Either way: not 200.
    assert r.status_code in (401, 403)


# ── Channel list endpoint ───────────────────────────────────────────────

def test_channels_lists_dm_group_and_internal(seeded_app):
    client, _anon, cid = seeded_app
    r = client.get(f"/community/{cid}/chat/channels")
    assert r.status_code == 200
    chans = r.json()["channels"]
    ids = {c["channel"] for c in chans }
    # The seeded persona DM (carries real rows) — present regardless of run order.
    assert "dm-agent-persona-001" in ids
    # Registered user-postable group channel is listed.
    assert "group-cafe" in ids
    # Internal (agent-to-agent) channels ARE listed — the owner watches them
    # ("Behind the scenes") — but flagged NOT postable so the composer locks.
    internal = [c for c in chans if c["channel"].startswith("internal-")]
    assert internal, "internal backchannel should be surfaced for the owner to watch"
    assert all(c["kind"] == "internal" for c in internal)
    assert all(c["postable"] is False for c in internal)
    # Genuine system/log mgr-* channels stay hidden (mgr-system-log / bare mgr).
    assert not any(c["channel"] in ("mgr-system-log", "mgr") for c in chans)
    # DM entries carry display metadata for rendering.
    dm = next(c for c in chans if c["channel"] == "dm-agent-persona-001")
    assert dm["kind"] == "dm"
    assert dm["agent_id"] == "agent-persona-001"
    assert dm["name"] == "소은"
    assert dm["avatar_url"] and "agent-persona-001" in dm["avatar_url"]


def test_channels_requires_auth(seeded_app):
    _client, anon, cid = seeded_app
    r = anon.get(f"/community/{cid}/chat/channels")
    assert r.status_code in (401, 403)


# ── Dispatcher is config-driven, NOT echo-forced ────────────────────────

def test_dispatcher_loads_agent_map_config(seeded_app, monkeypatch):
    """Echo selected via a DIFFERENT config key proves the dispatcher loads the
    community's real LLM-routing config, not a hardcoded GLIMI_LLM_BACKEND=echo.

    We reconfigure the community .env to route ``mgr → echo`` via
    ``GLIMI_LLM_AGENT_MAP`` (the per-agent-type mechanism) with NO bare
    ``GLIMI_LLM_BACKEND`` line, and assert the mgr turn still echoes. The only way
    that happens is if the adapter loaded the agent-map from the .env into the
    kernel's provider resolution — i.e. it is config-driven, not echo-forced.
    """
    import json
    import os as _os
    from community import community as comm
    client, _anon, cid = seeded_app
    env_path = comm.COMMUNITIES_DIR / cid / ".env"
    # Rewrite the .env to use the agent-map mechanism only (no bare backend line).
    env_path.write_text(
        "GLIMI_LLM_AGENT_MAP=" + json.dumps({"mgr": "echo"}) + "\n",
        encoding="utf-8",
    )
    # Clear any backend leaked into os.environ by a previous in-process turn so we
    # don't accidentally satisfy the route via a stale global.
    _os.environ.pop("GLIMI_LLM_BACKEND", None)
    _os.environ.pop("GLIMI_LLM_AGENT_MAP", None)
    monkeypatch.delenv("GLIMI_LLM_BACKEND", raising=False)

    sentinel = "ZZUNIQUESENTINEL42"
    with client.websocket_connect(f"/community/{cid}/chat/ws") as ws:
        ws.send_json({"type": "text", "channel": "dm-mgr", "agent": "mgr", "text": sentinel})
        frame = _drain_until_text(ws)
    assert frame is not None, "no reply with agent-map echo config"
    assert sentinel in frame["text"], (
        "mgr did not echo via GLIMI_LLM_AGENT_MAP → adapter is not loading the "
        "community's LLM-routing config"
    )


def test_dispatcher_source_has_no_backend_force():
    """Source-level guard: the dispatcher must not set GLIMI_LLM_BACKEND, and must
    call the runtime's streaming entry (delegating provider selection to the
    kernel's config-layering)."""
    import inspect
    from community.platform.routers import chat as chat_mod
    src = inspect.getsource(chat_mod)
    assert 'os.environ.setdefault("GLIMI_LLM_BACKEND"' not in src
    assert 'os.environ["GLIMI_LLM_BACKEND"]' not in src
    assert "generate_response_streaming" in src
    # The human turn must never be silently dropped. A DM turn lets the kernel log
    # it (default log_user_message=True). Group fan-out instead logs it ONCE up
    # front (_log_owner_turn) and suppresses per-agent kernel logging to avoid one
    # dup per responder — so if suppression appears, the explicit single-log must
    # appear too.
    if "log_user_message=False" in src:
        assert "_log_owner_turn" in src, (
            "fan-out suppresses kernel human-turn logging but does not log it once"
        )
