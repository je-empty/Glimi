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
    assert isinstance(tl["tool_calls"], list)  # envelope must match dashboard.js (reads d.tool_calls)


def test_snapshot_injects_workspace_title(client):
    # The shared dashboard hero reads community_meta.name → it must carry the workspace
    # title so the Overview/graph heading isn't blank.
    snap = client.get("/w/demo/api/snapshot").json()
    assert (snap.get("community_meta") or {}).get("name")   # non-empty


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


# ── persistence + per-agent detail + open create ─────────────────────────────

def test_created_workspace_persists_across_restart(monkeypatch, tmp_path):
    # User-created workspaces survive a restart: metadata persisted + deterministically
    # re-created on the echo backend.
    monkeypatch.setenv("GLIMI_WORKSPACES_STORE", str(tmp_path / "ws.json"))
    monkeypatch.setattr(server, "_USER_BACKEND", "echo")
    reg1 = server.WorkspaceRegistry()
    ws = reg1.create("수민", "오픈소스 런칭 기획")
    assert ws.id in [c["id"] for c in reg1.cards()]
    # simulate restart: a fresh registry restores from the persisted metadata
    reg2 = server.WorkspaceRegistry()
    server._restore_user_workspaces(reg2)
    cards = reg2.cards()
    restored = next((c for c in cards if c["id"] == ws.id), None)
    assert restored is not None                       # came back after "restart"
    assert restored["goal"] == "오픈소스 런칭 기획"
    assert restored["created_at"] == ws.created_at     # original timestamp preserved


def test_created_workspace_not_persisted_without_store(monkeypatch):
    # No store configured → in-memory only (unchanged default behavior).
    monkeypatch.delenv("GLIMI_WORKSPACES_STORE", raising=False)
    monkeypatch.setattr(server, "_USER_BACKEND", "echo")
    reg = server.WorkspaceRegistry()
    reg.create("X", "Y")
    reg2 = server.WorkspaceRegistry()
    server._restore_user_workspaces(reg2)
    assert [c for c in reg2.cards() if c["kind"] == "user"] == []


def test_agent_detail_page(client):
    # The workspace now has the full per-agent detail page (canonical agent_detail.html,
    # api_base-retargeted to /w/{id}, read-only → no model switch).
    r = client.get("/w/demo/agent/coordinator")
    assert r.status_code == 200
    body = r.text
    assert '__GLIMI_API_BASE__ = "/w/demo"' in body      # retargeted to the workspace API
    assert "__GLIMI_INTERACTIVE__ = false" in body        # read-only (model switch hidden)
    assert '__GLIMI_BACK__ = "/w/demo"' in body           # back-link to the dashboard


def test_create_workspace_open(client):
    # Creating a workspace is open (no invite gate) — it's the core product flow.
    r = client.post("/api/workspaces", json={"name": "Mia", "goal": "Plan the launch"})
    assert r.status_code == 200
    created = r.json()
    assert created["kind"] == "user" and created["goal"] == "Plan the launch"
    assert created["id"] in [c["id"] for c in client.get("/api/workspaces").json()]


def test_demo_only_blocks_create_and_hides_form(client, monkeypatch):
    # GLIMI_DEMO_ONLY (public showcase): only the seeded demo, no creation.
    monkeypatch.setattr(server, "_DEMO_ONLY", True)
    assert client.post("/api/workspaces", json={"name": "X", "goal": "Y"}).status_code == 403
    assert 'action="/api/workspaces"' not in client.get("/").text  # create form hidden


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
