"""Tests for the multi-workspace server (workspace/server.py).

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
_WS_DIR = os.path.join(_REPO, "glimi-workspace", "workspace")
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


def _wait_ready(client, ws_id, timeout=10.0):
    """Block until a freshly-created workspace's background build finishes.

    Create is now NON-BLOCKING: POST /api/workspaces returns immediately with
    ``status="building"`` and the team-forming + first round run on a background
    thread (streaming live to the dashboard). Tests that assert on the built team
    poll the snapshot's ``build.status`` to ``"ready"`` first, so correctness never
    depends on build timing. Returns the final snapshot."""
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        snap = client.get(f"/w/{ws_id}/api/snapshot").json()
        if (snap.get("build") or {}).get("status") == "ready":
            return snap
        _t.sleep(0.02)
    raise AssertionError(f"workspace {ws_id} never became ready within {timeout}s")


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
    # Card carries the counts the home page renders. 9 channels: the 4 DMs, the
    # 2 specialist-A2A internal channels, group-team, mgr-approvals, AND the
    # autonomous owner's read-only internal-owner reasoning channel.
    assert demo["agents"] == 4
    assert demo["channels"] == 9


def test_home_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    # The home page is the shared _demo_list.html — NOT a per-workspace dashboard,
    # so no data-api-base (that's only for /w/{id} dashboards).
    assert "data-api-base" not in body
    assert "Glimi Workspace" in body
    assert 'class="badge"' in body          # the demo card renders server-side
    assert "?lang=en" in body               # shared language toggle present
    # The old workspace-only "features" section is gone (unified with Community).
    assert "안에 들어있는" not in body and "What's inside" not in body


# ── creating a workspace adds one with an independent store ───────────────────

def test_create_adds_independent_workspace(client):
    before = client.get("/api/workspaces").json()
    r = client.post("/api/workspaces", json={"name": "Dana", "goal": "Ship the mobile beta"})
    assert r.status_code == 200
    created = r.json()
    new_id = created["id"]
    assert created["goal"] == "Ship the mobile beta"
    assert created["kind"] == "user"
    # Create is NON-BLOCKING: it returns immediately while the team-forming + first
    # round run on a background thread, so the card comes back status="building".
    assert created["status"] == "building"

    after = client.get("/api/workspaces").json()
    assert len(after) == len(before) + 1

    # The dashboard is reachable at /w/{id} the instant the record exists, even
    # mid-build (no 404/502 while the first round runs).
    assert client.get(f"/w/{new_id}").status_code == 200

    # The new workspace's store is INDEPENDENT of the Demo's: its own owner/goal,
    # built fresh — not the Demo's hand-authored Sam/launch transcript. Wait for the
    # background build to finish before asserting on the formed team.
    ns = _wait_ready(client, new_id)
    assert ns["owner_name"] == "Dana"
    ds = client.get("/w/demo/api/snapshot").json()
    assert ds["owner_name"]                       # demo has its own seeded owner
    assert ns["owner_name"] != ds["owner_name"]   # distinct stores → distinct owners
    # Same role topology (Coordinator + 3 specialists), distinct store instances.
    assert {a["id"] for a in ns["agents"]} == {"coordinator", "researcher", "builder", "critic"}


def test_create_is_nonblocking_and_streams_to_ready(client):
    # The big one: POST /api/workspaces must NOT run the first round synchronously.
    # It returns immediately with status="building"; the team forms + the first
    # round run on a background thread; /w/{id} is reachable instantly; and the
    # snapshot's build.status flips building→ready on its own (live, no extra call).
    r = client.post("/api/workspaces", json={"name": "Pat", "goal": "Plan the launch"})
    assert r.status_code == 200
    wid = r.json()["id"]
    assert r.json()["status"] == "building"

    # Reachable + reports building immediately (the dashboard renders mid-build).
    snap0 = client.get(f"/w/{wid}/api/snapshot").json()
    assert "build" in snap0 and snap0["build"]["status"] in ("building", "ready")
    assert client.get(f"/w/{wid}").status_code == 200

    # It reaches ready on its own (the background build finishes), and only THEN is
    # the full team + first-round transcript present.
    snap = _wait_ready(client, wid)
    assert snap["build"]["status"] == "ready"
    assert {a["id"] for a in snap["agents"]} == {"coordinator", "researcher", "builder", "critic"}
    # The first round actually ran: the owner's goal + replies are in dm-coordinator.
    hist = client.get(f"/w/{wid}/chat/history", params={"channel": "dm-coordinator"}).json()
    assert len(hist["messages"]) >= 2


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
    # 9 channels — see test_home_lists_demo (now includes internal-owner, the
    # autonomous owner's read-only reasoning channel).
    assert len(snap["channels"]) == 9
    assert any((c.get("channel") or c.get("name")) == "internal-owner" for c in snap["channels"])
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


def test_avatar_route_returns_role_emoji_svg(client):
    # The workspace avatar is a role EMOJI on a role-hued disc (not a 2-letter
    # monogram, not an anime face). Each role renders its own icon; always 200 SVG.
    for aid, emoji in (("coordinator", "🧭"), ("researcher", "🔬"),
                       ("builder", "🛠"), ("critic", "🔍")):
        r = client.get("/w/demo/api/avatar", params={"id": aid})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        body = r.text
        assert body.lstrip().startswith("<svg")
        assert emoji in body
    # An unknown id falls back to the generic teammate emoji (never a bare letter).
    r = client.get("/w/demo/api/avatar", params={"id": "mystery"})
    assert r.status_code == 200 and "🧩" in r.text


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


# ── autonomous owner-driver (auto-run) endpoints + channel surfacing ─────────

def test_chat_channels_surface_internal_owner(client):
    # The demo's chat channel list surfaces internal-owner as a read-only
    # ("Behind the scenes") channel with the friendly display name + tooltip.
    r = client.get("/w/demo/chat/channels")
    assert r.status_code == 200
    chans = r.json()["channels"]
    owner_ch = next((c for c in chans if c["channel"] == "internal-owner"), None)
    assert owner_ch is not None
    assert owner_ch["kind"] == "internal"
    assert owner_ch["postable"] is False         # read-only: the owner watches itself think
    assert owner_ch["name"] == "자동 진행 메모"     # friendly display name, not the raw id
    assert owner_ch["tooltip"] == "자동 진행(오너 대리) 시 매니저 검토 메모"

    # The Coordinator's DM is labelled "매니저" (the owner's single point of contact);
    # its underlying channel id stays dm-coordinator (load-bearing).
    coord_dm = next((c for c in chans if c["channel"] == "dm-coordinator"), None)
    assert coord_dm is not None
    assert coord_dm["name"] == "매니저"

    # Behind-the-scenes internal pair channels (coordinator↔specialist delegation
    # and specialist↔specialist A2A) surface as read-only with a friendly "A ↔ B"
    # label resolved from the two agent ids — NOT the raw channel id, and robust to
    # the multi-hyphen 'coordinator' side of internal-coordinator-<sid>.
    deleg = next((c for c in chans if c["channel"] == "internal-coordinator-researcher"), None)
    assert deleg is not None
    assert deleg["kind"] == "internal" and deleg["postable"] is False
    assert deleg["name"] == "매니저 ↔ 리서처"      # friendly pair label, not the raw id
    a2a = next((c for c in chans if c["channel"] == "internal-researcher-critic"), None)
    assert a2a is not None
    assert a2a["name"] == "리서처 ↔ 크리틱"
    # dm-researcher is OWNER↔specialist only — the demo never delegates there, so no
    # coordinator→researcher delegation leaked into a dm-* channel.
    deleg_channels = {c["channel"] for c in chans if c["kind"] == "internal"}
    assert "internal-coordinator-builder" in deleg_channels
    assert "internal-coordinator-critic" in deleg_channels


def test_auto_start_403_on_demo(client):
    # The public demo is read-only — it showcases the loop via the scripted unfold,
    # never the live driver. /auto/start must 403.
    r = client.post("/w/demo/auto/start", json={})
    assert r.status_code == 403


def test_auto_endpoints_404_on_unknown(client):
    assert client.post("/w/nope/auto/start", json={}).status_code == 404
    assert client.post("/w/nope/auto/stop").status_code == 404
    assert client.get("/w/nope/auto/status").status_code == 404


def test_auto_status_defaults_for_user_workspace(client):
    # A freshly created (writable) workspace reports auto-run OFF, no run in flight.
    created = client.post("/api/workspaces",
                          json={"name": "Ravi", "goal": "Plan the launch"}).json()
    wid = created["id"]
    st = client.get(f"/w/{wid}/auto/status").json()
    assert st["running"] is False
    assert st["auto_run"] is False
    assert st["rounds_run"] == 0
    assert st["reason"] is None
    assert st["max_rounds"] == 5


def test_auto_stop_idempotent_when_not_running(client):
    # /auto/stop on a workspace with no run in flight is a no-op, still ok.
    created = client.post("/api/workspaces",
                          json={"name": "Noa", "goal": "Ship it"}).json()
    wid = created["id"]
    r = client.post(f"/w/{wid}/auto/stop")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "running": False}


def test_snapshot_exposes_auto_block(client):
    # The snapshot carries an `auto` block so the chat UI can restore the toggle.
    created = client.post("/api/workspaces",
                          json={"name": "Ivy", "goal": "Write docs"}).json()
    wid = created["id"]
    auto = client.get(f"/w/{wid}/api/snapshot").json()["auto"]
    assert auto["writable"] is True
    assert auto["auto_run"] is False and auto["running"] is False
    # Demo snapshot reports writable False (read-only showcase).
    demo_auto = client.get("/w/demo/api/snapshot").json()["auto"]
    assert demo_auto["writable"] is False


def test_auto_run_full_loop_echo(monkeypatch, tmp_path):
    # End-to-end: arming auto-run on an echo workspace runs the bounded loop to
    # completion ($0), advancing rounds_run and recording a terminal reason. Driven
    # through the real /auto/start task (no chat WS needed — fan-out tolerates zero
    # subscribers), then polled to quiescence via /auto/status.
    import time
    monkeypatch.setattr(server, "_USER_BACKEND", "echo")
    app = server.create_app(demo_interval=3600.0)
    c = TestClient(app)
    created = c.post("/api/workspaces", json={"name": "수민", "goal": "오픈소스 런칭 기획"}).json()
    wid = created["id"]
    _wait_ready(c, wid)  # let the create build (team-forming + first round) finish first
    r = c.post(f"/w/{wid}/auto/start", json={"max_rounds": 3, "context": "정직한 기조"})
    assert r.status_code == 200
    assert r.json()["running"] is True and r.json()["max_rounds"] == 3
    # A second start while running → 409.
    # (race-tolerant: only assert if still running)
    for _ in range(100):
        st = c.get(f"/w/{wid}/auto/status").json()
        if not st["running"]:
            break
        time.sleep(0.05)
    st = c.get(f"/w/{wid}/auto/status").json()
    assert st["running"] is False
    assert st["rounds_run"] >= 1
    assert st["reason"] in ("done", "max_rounds")
    # The owner's reasoning landed in the read-only internal-owner channel.
    hist = c.get("/w/{}/chat/history".format(wid), params={"channel": "internal-owner"}).json()
    assert len(hist["messages"]) >= 1


# ── dynamic team: manager-proposed roster + runtime add + /team/add ──────────

def test_propose_roster_echo_returns_default():
    # On echo, the manager does NOT call the LLM — it returns the DEFAULT
    # researcher/builder/critic so create stays deterministic + backward-compat.
    import team
    from glimi import Glimi
    g = Glimi(backend="echo", owner_name="Owner")
    roster = team.propose_roster(g, "any goal", "Owner")
    ids = [r[0] for r in roster]
    assert ids == ["researcher", "builder", "critic"]


def test_seed_team_echo_is_default_team():
    # seed_team on echo builds exactly coordinator + the default 3 specialists —
    # the same topology the static TEAM produced (the backward-compat anchor).
    import run, team
    from glimi import Glimi
    g = Glimi(backend="echo", owner_name="Owner")
    added = run.seed_team(g, "Plan the launch", "Owner")
    assert added == ["researcher", "builder", "critic"]
    assert {a["id"] for a in g.store.list_agents()} == {
        "coordinator", "researcher", "builder", "critic"}
    # Default A2A pairs are byte-identical to the historical COLLAB_PAIRS topology.
    pairs = [(p[0], p[1], p[2]) for p in team.derive_pairs(g, added)]
    assert pairs == [
        ("researcher", "critic", "internal-researcher-critic"),
        ("builder", "researcher", "internal-builder-researcher"),
    ]


def test_propose_roster_dynamic_on_stubbed_backend(monkeypatch):
    # A stubbed real backend → the manager proposes a goal-appropriate roster, and
    # the orchestration derives dm-<role> channels + internal-* pairs for those ids.
    import run, team
    import glimi.llm as _llm
    import glimi.runtime as _rt
    from glimi import Glimi

    roster_json = (
        '[{"id":"researcher","name":"Researcher","role":"researcher","persona":"Finds facts."},'
        '{"id":"designer","name":"Designer","role":"designer","persona":"Owns the look."},'
        '{"id":"marketer","name":"Marketer","role":"marketing","persona":"Owns the message."}]'
    )

    class _Resp:
        text = roster_json
        error = None

    # The model/provider resolvers are MODULE-LEVEL functions; stub them so the
    # proposal takes the real path with a deterministic provider (claude → direct).
    monkeypatch.setattr(_rt, "_resolve_agent_model", lambda aid, atype: "claude-sonnet-4-6")
    monkeypatch.setattr(_rt, "_provider_for", lambda atype, model: "claude")
    monkeypatch.setattr(_llm, "generate", lambda **kw: _Resp())

    g = Glimi(backend="claude_cli", owner_name="Owner")
    added = run.seed_team(g, "Launch a design-heavy product", "Owner")
    assert added == ["researcher", "designer", "marketer"]
    assert {a["id"] for a in g.store.list_agents()} == {
        "coordinator", "researcher", "designer", "marketer"}
    # The live roster drives the derived delegation channels + A2A pairs.
    assert team.live_specialists(g) == ["researcher", "designer", "marketer"]
    # Delegation is behind-the-scenes (internal-coordinator-<id>), NOT a dm-<id>
    # (dm-<id> is reserved OWNER↔specialist).
    assert team.delegation_channel_for("designer") == "internal-coordinator-designer"
    pair_channels = {p[2] for p in team.derive_pairs(g, added)}
    assert "internal-researcher-designer" in pair_channels
    # The dynamic role's avatar emoji comes from its stored role keyword.
    assert (g.store.get_agent("designer") or {}).get("role_keyword") == "designer"
    assert server._role_emoji("designer", "designer") == "🎨"


def test_add_team_member_joins_next_round_echo():
    # add_team_member adds a specialist that (a) shows in the live roster and (b)
    # gets a dm-<id> channel + an emoji avatar on the next run_round.
    import run, team
    from glimi import Glimi
    g = Glimi(backend="echo", owner_name="Owner")
    run.seed_team(g, "Plan the launch", "Owner")
    assert run.add_team_member(g, "writer", "Writer", "Owns the words.", "writer") is True
    assert "writer" in team.live_specialists(g)
    # A reserved id or a collision is a no-op (never clobbers the manager/an id).
    assert run.add_team_member(g, "coordinator", "X", "Y", "") is False
    assert run.add_team_member(g, "writer", "X", "Y", "") is False
    # The next round wires the new specialist's delegation channel + group seat.
    # Delegation is behind-the-scenes (internal-coordinator-<id>), not a dm-<id>.
    run.run_round(g, "follow up", "Owner")
    overview = {c["channel"] for c in g.store.get_channel_overview()}
    assert "internal-coordinator-writer" in overview


def test_team_add_endpoint_happy_path(client):
    # POST /w/{id}/team/add on a writable workspace adds a specialist + returns its
    # card; the new agent then appears in /chat/channels with an emoji avatar.
    created = client.post("/api/workspaces",
                          json={"name": "Dana", "goal": "Ship the beta"}).json()
    wid = created["id"]
    _wait_ready(client, wid)  # team must be seeded before adding a member
    r = client.post(f"/w/{wid}/team/add",
                    json={"role": "designer", "name": "디자이너",
                          "persona": "Owns the visual identity.",
                          "role_keyword": "designer"})
    assert r.status_code == 200
    card = r.json()
    assert card["id"] == "designer" and card["channel"] == "dm-designer"
    # It shows up as a DM channel in the chat list.
    chans = client.get(f"/w/{wid}/chat/channels").json()["channels"]
    assert any(c["channel"] == "dm-designer" for c in chans)
    # Its avatar route renders the role emoji (🎨 from the stored keyword).
    av = client.get(f"/w/{wid}/api/avatar", params={"id": "designer"})
    assert av.status_code == 200 and "🎨" in av.text


def test_team_add_endpoint_gating(client):
    # 403 on the read-only demo; 409 on a reserved id / collision; 400 missing role.
    assert client.post("/w/demo/team/add", json={"role": "designer"}).status_code == 403
    created = client.post("/api/workspaces",
                          json={"name": "Lee", "goal": "Write docs"}).json()
    wid = created["id"]
    _wait_ready(client, wid)  # team must be seeded before the collision check
    assert client.post(f"/w/{wid}/team/add", json={"role": "coordinator"}).status_code == 409
    assert client.post(f"/w/{wid}/team/add", json={"role": "researcher"}).status_code == 409  # already on team
    assert client.post(f"/w/{wid}/team/add", json={}).status_code == 400
    assert client.post(f"/w/nope/team/add", json={"role": "x"}).status_code == 404


def test_manager_add_agent_gate_auto_approves():
    # The manager's mid-run +1 request is gated via approval.run_gate with the new
    # "add_agent" kind; under auto-run (non-interactive) it AUTO-approves, so the
    # add proceeds without a live owner. (The driver path; verified at the gate.)
    import driver
    from approval import ApprovalAction, ApprovalPolicy, run_gate, AUTO_APPROVED
    action = ApprovalAction(kind=driver.ADD_AGENT_KIND, summary="add designer",
                            proposed_text="Owns the look.", channel="internal-owner",
                            metadata={"role": "designer", "name": "Designer"})
    outcome = run_gate(action, ApprovalPolicy.auto_approve_all(), interactive=False)
    assert outcome.decision == AUTO_APPROVED
    assert outcome.final_text == "Owns the look."


# ── the JS data-api-base default keeps the standalone dashboard unchanged ─────

def test_dashboard_js_api_base_defaults_empty():
    """Structural check: the one additive JS change defaults API_BASE to "" when
    <body data-api-base> is absent — so every single-store dashboard (Community
    Core, the standalone workspace --serve/--demo) keeps its absolute /api/* paths.
    """
    js_path = os.path.join(_REPO, "glimi-core", "glimi", "dashboard", "static", "js", "dashboard.js")
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
