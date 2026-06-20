"""Tests for the multi-workspace server (apps/workspace/server.py).

One Workspace server hosts N workspaces, parallel to the Community platform's
"one process → N communities". Covered here:

- the registry holds the read-only Demo by default;
- ``GET /api/workspaces`` lists it;
- creating a workspace adds one whose store is INDEPENDENT (its own agents/goal,
  separate from the Demo's);
- ``/w/{id}/api/snapshot`` returns that workspace's data, with the same shape as
  the standalone Core dashboard's ``/api/snapshot``;
- an unknown id 404s;
- the dashboard JS ``data-api-base`` default is ``""`` — so the standalone
  single-store dashboard keeps using absolute ``/api/*`` paths, unchanged.

Kernel-only: imports ``glimi`` + the app's ``server`` module + FastAPI's
``TestClient``, never ``src`` / Discord.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

# CI installs the kernel only; fastapi/httpx (TestClient) may be absent → skip
# this whole module gracefully, matching the other web tests.
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

# Make the flat-dir app modules (server, demo, run, team) importable like run.py.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WS_DIR = os.path.join(_REPO, "apps", "workspace")
if _WS_DIR not in sys.path:
    sys.path.insert(0, _WS_DIR)

# Workspace is English-default; the create path drives A2A turns.
os.environ.setdefault("GLIMI_LANG", "en")

import server  # noqa: E402


@pytest.fixture()
def client():
    # demo_interval large so the live loop never fires during a test run (the
    # daemon thread just sleeps); the seeded demo population is present regardless.
    app = server.create_app(demo_interval=3600.0)
    return TestClient(app)


# ── the registry holds the Demo by default ───────────────────────────────────

def test_registry_holds_demo_by_default():
    reg = server.WorkspaceRegistry()
    server._install_demo(reg, interval=3600.0)
    demo_ws = reg.get("demo")
    assert demo_ws is not None
    assert demo_ws.kind == "demo"
    # The seeded launch team: Coordinator + 3 specialists.
    snap = demo_ws.reader().snapshot()
    assert len(snap["agents"]) == 4


def test_home_lists_demo(client):
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    cards = r.json()
    assert any(c["id"] == "demo" and c["kind"] == "demo" for c in cards)
    demo = next(c for c in cards if c["id"] == "demo")
    # Card carries the counts the home page renders.
    assert demo["agents"] == 4
    assert demo["channels"] == 8


def test_home_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    # The home page is its own template — NOT a per-workspace dashboard, so it must
    # not carry a data-api-base (that attribute is only for /w/{id} dashboards).
    assert "data-api-base" not in r.text
    assert "Glimi Workspace" in r.text


# ── creating a workspace adds one with an independent store ───────────────────

def test_create_adds_independent_workspace(client):
    before = client.get("/api/workspaces").json()
    r = client.post("/api/workspaces", json={"name": "Dana", "goal": "Ship the mobile beta"})
    assert r.status_code == 200
    created = r.json()
    new_id = created["id"]
    assert created["goal"] == "Ship the mobile beta"
    assert created["kind"] == "user"

    after = client.get("/api/workspaces").json()
    assert len(after) == len(before) + 1

    # The new workspace's store is INDEPENDENT of the Demo's: its own owner/goal,
    # built fresh — not the Demo's hand-authored Sam/launch transcript.
    ns = client.get(f"/w/{new_id}/api/snapshot").json()
    assert ns["owner_name"] == "Dana"
    ds = client.get("/w/demo/api/snapshot").json()
    assert ds["owner_name"]                       # demo has its own seeded owner
    assert ns["owner_name"] != ds["owner_name"]   # distinct stores → distinct owners
    # Same role topology (Coordinator + 3 specialists), distinct store instances.
    assert {a["id"] for a in ns["agents"]} == {"coordinator", "researcher", "builder", "critic"}


def test_create_via_form_redirects(client):
    r = client.post(
        "/api/workspaces",
        data={"name": "Lee", "goal": "Write the docs"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/w/")


# ── per-workspace dashboard endpoints ────────────────────────────────────────

def test_demo_snapshot_shape_matches_core(client):
    snap = client.get("/w/demo/api/snapshot").json()
    # Same shape as glimi/dashboard/app.py's /api/snapshot (graph + owner identity).
    assert set(["agents", "channels", "relationships", "owner_name", "owner_ids"]) <= set(snap.keys())
    assert len(snap["agents"]) == 4
    assert len(snap["channels"]) == 8
    assert snap["owner_name"]   # seeded owner identity present (content-agnostic)


def test_demo_other_endpoints(client):
    # usage populated (echo turns at $0, all estimated — the demo's honest panel).
    u = client.get("/w/demo/api/usage").json()
    assert u["call_count_month"] > 0
    assert u["spend_month"] == 0.0
    # agent_detail + channel + tool_timeline all 200 with the right shapes.
    ad = client.get("/w/demo/api/agent_detail", params={"id": "coordinator"}).json()
    assert ad["id"] == "coordinator"
    ch = client.get("/w/demo/api/channel", params={"name": "group-team"}).json()
    assert ch["name"] == "group-team"
    assert "messages" in ch
    tl = client.get("/w/demo/api/tool_timeline").json()
    assert isinstance(tl, list)


def test_dashboard_html_injects_api_base(client):
    # The Core dashboard (graph/overview) now lives at /w/{id}/graph; /w/{id}
    # itself is the community-style chat view. The graph view is the one served
    # from the shared Core index, retargeted to this workspace's endpoints.
    h = client.get("/w/demo/graph")
    assert h.status_code == 200
    assert 'data-api-base="/w/demo"' in h.text
    assert 'data-refresh-ms="6000"' in h.text


def test_unknown_id_404s(client):
    assert client.get("/w/nope/api/snapshot").status_code == 404
    assert client.get("/w/nope").status_code == 404
    assert client.get("/w/nope/api/usage").status_code == 404


# ── presenter demo: chat-enabled twin of the public read-only demo ───────────

def test_presenter_unlisted_but_reachable(client):
    # The presenter twin is NOT on the public home list (cards() skips it) — the
    # public surface stays just the read-only demo — but it IS reachable by URL
    # and seeded from the SAME launch team (4 agents, 8 channels).
    ids = {c["id"] for c in client.get("/api/workspaces").json()}
    assert "demo" in ids
    assert "demo-live" not in ids
    snap = client.get("/w/demo-live/api/snapshot").json()
    assert len(snap["agents"]) == 4
    assert len(snap["channels"]) == 8


def test_presenter_chat_enabled_demo_readonly(client):
    # Public demo page: read-only flag true, no reset control.
    demo = client.get("/w/demo").text
    assert re.search(r"__GLIMI_READONLY__\s*=\s*true", demo)
    assert "presenter-reset" not in demo
    # Presenter page: read-only flag false (chat on) + the reset control present.
    live = client.get("/w/demo-live").text
    assert re.search(r"__GLIMI_READONLY__\s*=\s*false", live)
    assert "presenter-reset" in live


def test_presenter_reset_only_for_presenter(client):
    # Reset rebuilds the presenter back to the seeded state (still 4 agents).
    r = client.post("/w/demo-live/reset")
    assert r.status_code == 200 and r.json()["status"] == "reset"
    assert len(client.get("/w/demo-live/api/snapshot").json()["agents"]) == 4
    # The public demo + user workspaces can't be reset; unknown id 404s.
    assert client.post("/w/demo/reset").status_code == 403
    created = client.post("/api/workspaces", json={"name": "Mia", "goal": "X"}).json()
    assert client.post(f"/w/{created['id']}/reset").status_code == 403
    assert client.post("/w/nope/reset").status_code == 404


def test_presenter_ws_accepts_owner_turn(client):
    # Demo socket rejects owner text (read-only); the presenter socket accepts it.
    with client.websocket_connect("/w/demo/chat/ws") as sock:
        sock.send_json({"type": "text", "channel": "dm-coordinator", "text": "hi"})
        assert sock.receive_json().get("error") == "demo_readonly"
    with client.websocket_connect("/w/demo-live/chat/ws") as sock:
        sock.send_json({"type": "text", "channel": "dm-coordinator", "text": "hi"})
        saw_readonly = got_response = False
        for _ in range(8):
            msg = sock.receive_json()
            if msg.get("error") == "demo_readonly":
                saw_readonly = True
                break
            if msg.get("type") in ("typing", "text"):
                got_response = True
                if msg.get("type") == "text":
                    break
            if msg.get("type") == "typing" and msg.get("on") is False:
                break
        assert not saw_readonly  # chat is enabled on the presenter
        assert got_response


# ── invite gating (presenter chat + workspace creation) ─────────────────────

def test_invite_gate_off_by_default(client):
    # No GLIMI_INVITE_TOKENS configured → presenter chat is open (gate disabled).
    assert re.search(r"__GLIMI_READONLY__\s*=\s*false", client.get("/w/demo-live").text)


def test_invite_gate_blocks_guests_without_token(client, monkeypatch):
    monkeypatch.setattr(server, "_INVITE_TOKENS", {"SECRET"})
    # presenter without a token → read-only (chat locked)
    assert re.search(r"__GLIMI_READONLY__\s*=\s*true", client.get("/w/demo-live").text)
    # with a valid token → chat unlocked (+ cookie remembered)
    r = client.get("/w/demo-live?invite=SECRET")
    assert re.search(r"__GLIMI_READONLY__\s*=\s*false", r.text)
    assert "glimi_invite" in r.headers.get("set-cookie", "")
    # the public read-only demo is never affected by the invite gate
    assert re.search(r"__GLIMI_READONLY__\s*=\s*true", client.get("/w/demo").text)


def test_invite_gate_blocks_create_without_token(client, monkeypatch):
    monkeypatch.setattr(server, "_INVITE_TOKENS", {"SECRET"})
    assert client.post("/api/workspaces", json={"name": "X", "goal": "Y"}).status_code == 403
    assert client.post("/api/workspaces?invite=SECRET",
                       json={"name": "X", "goal": "Y"}).status_code == 200


def test_invite_gate_owner_via_cf_header(client, monkeypatch):
    monkeypatch.setattr(server, "_INVITE_TOKENS", {"SECRET"})
    monkeypatch.setattr(server, "_OWNER_EMAIL", "owner@example.com")
    # CF Access verified the owner's email → chat unlocked without any token
    r = client.get("/w/demo-live",
                   headers={"Cf-Access-Authenticated-User-Email": "owner@example.com"})
    assert re.search(r"__GLIMI_READONLY__\s*=\s*false", r.text)
    # a different CF email is NOT the owner → still gated
    r2 = client.get("/w/demo-live",
                    headers={"Cf-Access-Authenticated-User-Email": "someone@else.com"})
    assert re.search(r"__GLIMI_READONLY__\s*=\s*true", r2.text)


def test_invite_tokens_from_file_live(client, monkeypatch, tmp_path):
    # File-based tokens are re-read per request → issue/revoke with no restart.
    f = tmp_path / "invite_tokens.txt"
    f.write_text("# issued links\nFILETOKEN  # alice 2026-06-20\n")   # inline label (helper format)
    monkeypatch.setattr(server, "_INVITE_TOKENS", set())          # env empty
    monkeypatch.setattr(server, "_INVITE_TOKENS_FILE", str(f))
    assert re.search(r"__GLIMI_READONLY__\s*=\s*false", client.get("/w/demo-live?invite=FILETOKEN").text)
    assert re.search(r"__GLIMI_READONLY__\s*=\s*true", client.get("/w/demo-live?invite=NOPE").text)
    # rotate the file (revoke FILETOKEN, issue OTHER) — no restart
    f.write_text("OTHER  # bob\n")
    assert re.search(r"__GLIMI_READONLY__\s*=\s*true", client.get("/w/demo-live?invite=FILETOKEN").text)
    assert re.search(r"__GLIMI_READONLY__\s*=\s*false", client.get("/w/demo-live?invite=OTHER").text)


def test_home_invite_sets_cookie_for_create(client, monkeypatch):
    # "start fresh" link /?invite=TOKEN remembers the token so create is unlocked.
    monkeypatch.setattr(server, "_INVITE_TOKENS", {"SECRET"})
    assert "glimi_invite" in client.get("/?invite=SECRET").headers.get("set-cookie", "")


# ── web admin panel (token management) ──────────────────────────────────────

def test_admin_panel_login_and_token_crud(client, monkeypatch, tmp_path):
    import invites  # the app's flat-dir module (server imports it as _invites)
    monkeypatch.setattr(invites, "_ADMIN_PW", "pw123")
    monkeypatch.setattr(invites, "_SECRET", "test-secret")
    monkeypatch.setattr(invites, "_STORE_PATH", str(tmp_path / "tok.json"))
    # not authed → login form
    r = client.get("/admin")
    assert r.status_code == 200 and "로그인" in r.text
    # wrong password → redirected back with error flag
    bad = client.post("/admin/login", data={"password": "nope"}, follow_redirects=False)
    assert bad.status_code == 303 and "e=1" in bad.headers["location"]
    # correct password → session cookie set
    ok = client.post("/admin/login", data={"password": "pw123"}, follow_redirects=False)
    assert ok.status_code == 303 and "glimi_admin" in ok.headers.get("set-cookie", "")
    # issue a token (session cookie carried by the TestClient) → becomes a live gate token
    client.post("/admin/issue", data={"label": "alice", "kind": "continue"})
    toks = invites.token_set()
    assert len(toks) == 1
    tok = next(iter(toks))
    assert re.search(r"__GLIMI_READONLY__\s*=\s*false", client.get(f"/w/demo-live?invite={tok}").text)
    # revoke → token gone
    client.post("/admin/revoke", data={"token": tok})
    assert invites.token_set() == set()


def test_admin_disabled_without_password(client, monkeypatch):
    import invites
    monkeypatch.setattr(invites, "_ADMIN_PW", "")
    r = client.get("/admin")
    assert r.status_code == 200 and "비활성화" in r.text
    # issue is rejected when not authed
    assert client.post("/admin/issue", data={"label": "x"}).status_code == 403


# ── the JS data-api-base default keeps the standalone dashboard unchanged ─────

def test_dashboard_js_api_base_defaults_empty():
    """Structural check: the one additive JS change defaults API_BASE to "" when
    <body data-api-base> is absent — so every single-store dashboard (Community
    Core, the standalone workspace --serve/--demo) keeps its absolute /api/* paths.
    """
    js_path = os.path.join(_REPO, "glimi", "dashboard", "static", "js", "dashboard.js")
    with open(js_path, encoding="utf-8") as f:
        js = f.read()
    # API_BASE reads <body data-api-base> and defaults to "" when absent.
    assert "getAttribute('data-api-base')" in js
    assert "const API_BASE" in js and "|| ''" in js
    # Every /api/* fetch is prefixed with API_BASE (none left bare via fetchJson).
    assert not re.search(r'fetchJson\(\s*[`"]/api/', js), "found an unprefixed /api/ fetch"
    assert js.count("API_BASE") >= 7  # the const + the fetch prefixes


def test_standalone_dashboard_unchanged_absolute_paths():
    """When data-api-base is absent (the standalone serve path), the JS falls back
    to absolute /api/* — verified end-to-end against the Core dashboard app."""
    from glimi import Glimi
    from glimi.dashboard.app import create_app_for_store

    g = Glimi(backend="echo", owner_name="Owner")
    g.add_agent("nova", persona="A curious companion.")
    g.reply("nova", "hi")
    c = TestClient(create_app_for_store(g.store))
    html = c.get("/").text
    # Standalone index carries no data-api-base → API_BASE="" → absolute paths.
    assert "data-api-base" not in html
    # And those absolute endpoints exist + respond on the standalone app.
    assert c.get("/api/snapshot").status_code == 200
    assert c.get("/api/usage").status_code == 200
