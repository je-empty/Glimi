"""Public read-only demo viewing — the anonymous showcase gate.

The whole platform is login-gated per-route (FastAPI ``Depends``). This feature
loosens ONLY the READ routes the demo needs, and ONLY for a community flagged
``read_only`` in the registry. The single predicate everywhere is:

    anon allowed  ⟺  is_read_only(target_community_id)   (reads only)

These tests pin that predicate at two levels:
  (a) the helper ``auth.public_readonly_user`` directly — the source of truth;
  (b) a few route-level checks via TestClient — anon 200 on the demo's read
      surface, anon 401 on the SAME read for a non-read_only community (no
      cross-community leak), and anon 401 on a write (mutations stay locked).
"""
import shutil
import tempfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import HTTPException, Request
from starlette.testclient import TestClient


# ── shared: an isolated communities/ tree with a read_only demo + a private one ──

def _write_registry(registry_path, *, default="private"):
    registry_path.write_text(
        f'default = "{default}"\n\n'
        '[community.demo]\n'
        'name = "데모"\n'
        'description = "mockup"\n'
        'language = "ko"\n'
        'read_only = true\n\n'
        '[community.private]\n'
        'name = "Private"\n'
        'description = ""\n'
        'language = "en"\n',
        encoding="utf-8",
    )


@pytest.fixture()
def isolated_registry(monkeypatch, tmp_path):
    """Point src.community at a tmp communities/ dir with demo(read_only) +
    private(normal), both with real dirs so existence checks pass."""
    from src import community as comm

    cdir = tmp_path / "communities"
    (cdir / "demo").mkdir(parents=True)
    (cdir / "private").mkdir(parents=True)
    registry = cdir / "registry.toml"
    _write_registry(registry)
    monkeypatch.setattr(comm, "COMMUNITIES_DIR", cdir)
    monkeypatch.setattr(comm, "REGISTRY_PATH", registry)
    monkeypatch.setattr(comm, "_current_id", None)
    monkeypatch.delenv("GLIMI_COMMUNITY", raising=False)
    return comm, cdir, registry


def _fake_request(path="/api/snapshot", query="", cookies=None, accept="application/json"):
    """A minimal ASGI Request with no session cookie (anon) unless given."""
    headers = [(b"accept", accept.encode())]
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie_str.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": headers,
    }
    return Request(scope)


# ── (a) helper-level predicate: anon ⟺ is_read_only ───────────────────────────

def test_helper_allows_anon_on_read_only(isolated_registry):
    """Anonymous + read_only community → returns None (allowed anon viewer)."""
    from src.platform.auth import public_readonly_user
    req = _fake_request()
    assert public_readonly_user(req, "demo") is None


def test_helper_blocks_anon_on_non_read_only_api(isolated_registry):
    """Anonymous + non-read_only community + API request → 401 (same failure as
    require_user for an /api/ path)."""
    from src.platform.auth import public_readonly_user
    req = _fake_request(path="/api/snapshot", accept="application/json")
    with pytest.raises(HTTPException) as ei:
        public_readonly_user(req, "private")
    assert ei.value.status_code == 401


def test_helper_blocks_anon_on_non_read_only_html_redirect(isolated_registry):
    """Anonymous + non-read_only + HTML request → 307 redirect to /login (same
    failure as require_user for a browser navigation)."""
    from src.platform.auth import public_readonly_user
    req = _fake_request(path="/community/private", query="", accept="text/html")
    with pytest.raises(HTTPException) as ei:
        public_readonly_user(req, "private")
    assert ei.value.status_code == 307
    assert ei.value.headers["Location"].startswith("/login")


def test_helper_anon_never_crosses_to_non_read_only(isolated_registry):
    """The predicate binds to the SPECIFIC target community: anon may view demo
    but the SAME anon is rejected for private — no cross-community allowance."""
    from src.platform.auth import public_readonly_user
    assert public_readonly_user(_fake_request(), "demo") is None
    with pytest.raises(HTTPException):
        public_readonly_user(_fake_request(), "private")


def test_helper_logged_in_non_member_403_even_on_read_only(isolated_registry, monkeypatch):
    """A logged-in NON-member still gets 403 (unchanged member gate) — read_only
    does not downgrade a real user's access check."""
    from src.platform import auth

    fake_user = {"id": 99, "username": "outsider", "role": "user"}
    monkeypatch.setattr(auth, "get_current_user", lambda req: fake_user)
    monkeypatch.setattr(auth.accounts, "user_can_access", lambda u, cid: False)
    with pytest.raises(HTTPException) as ei:
        auth.public_readonly_user(_fake_request(), "demo")
    assert ei.value.status_code == 403


# ── (b) route-level: anon 200 on demo read, 401 on non-read_only read + writes ──

@pytest.fixture()
def client_app(monkeypatch, tmp_path):
    """Real FastAPI app over an isolated data dir + a communities/ tree with a
    read_only demo (seeded DB) and a non-read_only private. Yields (anon, comm)."""
    data_dir = tempfile.mkdtemp(prefix="glimi-pubdemo-test-")
    monkeypatch.setenv("GLIMI_DATA_DIR", data_dir)

    from src import community as comm
    cdir = comm.COMMUNITIES_DIR

    demo_pre = (cdir / "demo").exists()
    priv_pre = (cdir / "private").exists()
    (cdir / "demo" / "logs").mkdir(parents=True, exist_ok=True)
    (cdir / "private" / "logs").mkdir(parents=True, exist_ok=True)

    # Flag demo read_only + private normal in the (real) registry, restoring after.
    registry = comm.REGISTRY_PATH
    orig_registry = registry.read_text(encoding="utf-8") if registry.exists() else None
    from src.platform.demo_seed import _write_registry_block
    comm._ensure_registry("demo")
    comm._ensure_registry("private")
    _write_registry_block("demo", "데모", "mockup", language="ko", read_only=True)
    _write_registry_block("private", "Private", "", language="en", read_only=False)

    # Seed a tiny demo DB so snapshot/agent/channel resolve real rows.
    monkeypatch.setenv("GLIMI_COMMUNITY", "demo")
    comm.set_community("demo")
    import src.db as db
    db.DB_PATH = None
    db.init_db()
    db.save_agent_profile({"id": "mgr", "type": "mgr", "name": "유나"})
    db.save_agent_profile({"id": "agent-persona-001", "type": "persona", "name": "소은"})
    db.save_user({"id": "owner", "name": "오너"})
    db.log_message("dm-agent-persona-001", "owner", "안녕")
    db.log_message("dm-agent-persona-001", "agent-persona-001", "안녕하세요!")

    from src.platform.app import app
    anon = TestClient(app)
    try:
        yield anon, comm
    finally:
        if not demo_pre:
            shutil.rmtree(cdir / "demo", ignore_errors=True)
        if not priv_pre:
            shutil.rmtree(cdir / "private", ignore_errors=True)
        if orig_registry is not None:
            registry.write_text(orig_registry, encoding="utf-8")
        shutil.rmtree(data_dir, ignore_errors=True)


def test_route_anon_200_on_demo_snapshot(client_app):
    anon, _comm = client_app
    r = anon.get("/api/snapshot?community=demo")
    assert r.status_code == 200, r.text
    assert r.json().get("community_id") == "demo"


def test_route_anon_401_on_private_snapshot(client_app):
    """Same read endpoint, a NON-read_only community → anon blocked (no leak)."""
    anon, _comm = client_app
    r = anon.get(
        "/api/snapshot?community=private",
        headers={"accept": "application/json"},
    )
    assert r.status_code == 401, r.text


def test_route_anon_401_on_post_action_even_demo(client_app):
    """Writes stay locked for anon — even targeting the read_only demo. The
    mutation route is not in the public-readonly opt-in set."""
    anon, _comm = client_app
    r = anon.post(
        "/api/action/run_sync?community=demo",
        headers={"accept": "application/json"},
        json={},
    )
    assert r.status_code == 401, r.text


def test_route_anon_401_on_list_communities(client_app):
    """The community LIST must never enumerate for anon (no list exposure)."""
    anon, _comm = client_app
    r = anon.get("/api/communities", headers={"accept": "application/json"})
    assert r.status_code == 401, r.text


def test_route_anon_avatar_demo_ok_private_blocked(client_app):
    anon, _comm = client_app
    ok = anon.get("/api/avatar?community=demo&id=mgr")
    assert ok.status_code == 200, ok.text
    blocked = anon.get(
        "/api/avatar?community=private&id=mgr",
        headers={"accept": "application/json"},
    )
    assert blocked.status_code == 401, blocked.text


def test_route_anon_chat_history_demo_ok_private_blocked(client_app):
    anon, _comm = client_app
    ok = anon.get("/community/demo/chat/history?channel=dm-agent-persona-001")
    assert ok.status_code == 200, ok.text
    blocked = anon.get(
        "/community/private/chat/history?channel=dm-mgr",
        headers={"accept": "application/json"},
    )
    assert blocked.status_code == 401, blocked.text
