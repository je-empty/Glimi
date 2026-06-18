"""apps/workspace/server.py — one Workspace server hosting N workspaces.

The Workspace analogue of the Community platform's "one process → N communities":
a single FastAPI server that owns a :class:`WorkspaceRegistry` and serves, for
each workspace, the SAME read-only Core dashboard (``glimi/dashboard``) under a
per-id prefix ``/w/{id}``.

Three things live here:

1. A **Demo** workspace, always present, read-only + visibly live — the seeded
   launch team from :mod:`demo`, with its ``activity_loop`` running on a daemon
   thread (so the dashboard keeps updating with zero setup, offline, $0).
2. A **home** page (``templates/home.html``) listing every workspace as a card and
   a "create workspace" form (name + goal).
3. **User-created** workspaces: ``POST /api/workspaces`` constructs a fresh
   ``Glimi(backend="echo")``, builds the real interaction topology via
   ``run.run_workspace`` (echo → fast, deterministic, a genuine interaction web),
   and registers it.

Kernel-only boundary, like the rest of Glimi Workspace: imports ``glimi``,
``fastapi``, and stdlib — never ``src`` / Discord.

The global-singleton constraint
-------------------------------
The kernel's runtime WRITE path is a process global (``glimi.runtime._store``,
set by ``Glimi.__init__``). The dashboard READ path is store-explicit
(``DashboardReader(store)``), so N stores are viewed independently and safely.
But any code that calls ``runtime.generate_*`` writes to whatever store was wired
last. So:

- Reads (every ``/w/{id}/api/*`` endpoint) build a per-request reader on that
  workspace's store — fully independent, any number in parallel.
- Builds (``run_workspace``, which DOES call ``runtime.generate_*``) are
  SERIALIZED under one lock: constructing each ``Glimi`` re-points the global to
  its own store, so only one build may run at a time. Echo makes a build instant.
- The Demo's ``activity_loop`` mutates ``g.store`` directly and never calls
  ``runtime.generate_*``, so it is safe to run alongside reads + serialized builds.

Run it (needs ``pip install "glimi[dashboard]"``)::

    PYTHONPATH=. python apps/workspace/run.py --server     # → http://127.0.0.1:8800
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

import glimi.dashboard as _dashboard
from glimi import Glimi
from glimi.dashboard import DashboardReader

# The Core dashboard's web-layer helpers (read-only endpoints' exact shapes) and
# the templates/static it ships. Reusing them keeps every workspace's dashboard
# byte-identical to the standalone one.
from glimi.dashboard.app import _channel_detail, _owner_info

# Import the sibling app modules the same dual-path way run.py does, so this works
# whether loaded as ``apps.workspace.server`` or from a flat dir on sys.path.
try:  # script / flat-dir on sys.path
    import demo as _demo  # type: ignore
    from run import run_workspace  # type: ignore
    from team import TEAM  # type: ignore
except ImportError:  # imported as apps.workspace.server
    from . import demo as _demo
    from .run import run_workspace
    from .team import TEAM

# Locate the Core dashboard's static + index template (reused, never modified).
_DASH_DIR = Path(_dashboard.__file__).resolve().parent
_DASH_STATIC = _DASH_DIR / "static"
_DASH_INDEX = _DASH_DIR / "templates" / "index.html"

# This app's own templates + static (the chat UI lives entirely in this layer —
# the kernel store gains no image/chat concerns).
_APP_DIR = Path(__file__).resolve().parent
_HOME_HTML = _APP_DIR / "templates" / "home.html"
_WS_DASH_HTML = _APP_DIR / "templates" / "ws_dashboard.html"
_CHAT_SHELL_HTML = _APP_DIR / "templates" / "_chat_shell.html"
_WS_STATIC = _APP_DIR / "static"


def _asset_ver() -> str:
    """Cache-busting token = short hash of the newest chat-asset mtime across BOTH
    the workspace-local static (tokens.css) and the canonical kernel dashboard
    static (chat.js/chat.css live there now). Appended to the chat URLs so a
    returning visitor never gets a stale copy, while still caching within a
    release. Recomputed at import, so it changes only when assets do."""
    try:
        latest = max(
            (p.stat().st_mtime
             for d in (_WS_STATIC, _DASH_STATIC)
             for p in d.rglob("*") if p.is_file()),
            default=0.0,
        )
    except Exception:
        latest = 0.0
    return hashlib.sha1(f"{latest}".encode("utf-8")).hexdigest()[:8]


_ASSET_VER = _asset_ver()

# Workspace chat avatars are role-based MONOGRAMS, not persona/anime faces. The
# workspace team is functional (Coordinator / Researcher / Builder / Critic), so
# a clean initial-on-tinted-disc reads better than a stock portrait — and keeps
# the avatar route dependency-free (no asset pool, always 200).
_ROLE_MONOGRAM = {
    "coordinator": "Co", "researcher": "Re", "builder": "Bu", "critic": "Cr",
}


def _monogram(agent_id: str) -> str:
    """A 1–2 char monogram for an agent id — role-aware and collision-free
    (Coordinator→Co, Critic→Cr, so the two C-roles never clash)."""
    s = (agent_id or "").strip()
    if not s:
        return "·"
    if s.lower() in _ROLE_MONOGRAM:
        return _ROLE_MONOGRAM[s.lower()]
    parts = [p for p in s.replace("_", " ").replace("-", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1]).upper()
    return (s[:1].upper() + s[1:2].lower()) if len(s) >= 2 else s[:1].upper()


def _avatar_svg(agent_id: str) -> str:
    """Inline SVG avatar: the agent's monogram on a deterministic tinted disc.
    Always renders — no external asset, so the avatar route is always 200."""
    mono = _monogram(agent_id)
    # Deterministic hue from the id so distinct agents read apart.
    hue = int(hashlib.sha1((agent_id or "").encode("utf-8")).hexdigest(), 16) % 360
    fs = 40 if len(mono) >= 2 else 46
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" '
        'viewBox="0 0 96 96" role="img">'
        f'<rect width="96" height="96" rx="48" fill="hsl({hue},42%,84%)"/>'
        f'<text x="48" y="50" font-family="-apple-system,Segoe UI,Roboto,sans-serif" '
        f'font-size="{fs}" font-weight="600" fill="hsl({hue},48%,30%)" '
        f'text-anchor="middle" dominant-baseline="central">{_esc(mono)}</text>'
        '</svg>'
    )


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── registry ──────────────────────────────────────────────────────────────────

@dataclass
class Workspace:
    """One hosted workspace: its Glimi (→ store) plus display metadata."""

    id: str
    glimi: Glimi
    title: str
    goal: str
    kind: str  # "demo" | "user"
    created_at: str = field(default_factory=_now_utc_iso)

    @property
    def store(self):
        return self.glimi.store

    def reader(self) -> DashboardReader:
        """A fresh store-explicit reader for this workspace (read path is safe)."""
        return DashboardReader(self.store)

    def card(self) -> dict:
        """The summary shape the home page's cards consume."""
        snap = self.reader().snapshot()
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "kind": self.kind,
            "agents": len(snap.get("agents", [])),
            "channels": len(snap.get("channels", [])),
            "created_at": self.created_at,
        }


class WorkspaceRegistry:
    """In-memory ``id -> Workspace`` map. A lock serializes LIVE builds (the
    create path calls ``runtime.generate_*``, which writes the process-global
    store — see the module docstring). Reads need no lock (store-explicit)."""

    def __init__(self) -> None:
        self._by_id: dict[str, Workspace] = {}
        self._lock = threading.Lock()  # serializes builds (global-singleton WRITE)
        self._seq = 0

    def get(self, ws_id: str) -> Optional[Workspace]:
        return self._by_id.get(ws_id)

    def cards(self) -> list[dict]:
        """Demo first, then user workspaces oldest → newest."""
        demos = [w for w in self._by_id.values() if w.kind == "demo"]
        users = [w for w in self._by_id.values() if w.kind != "demo"]
        users.sort(key=lambda w: w.created_at)
        return [w.card() for w in (*demos, *users)]

    def register(self, ws: Workspace) -> None:
        self._by_id[ws.id] = ws

    def _next_user_id(self) -> str:
        self._seq += 1
        return f"ws{self._seq}"

    def create(self, name: str, goal: str) -> Workspace:
        """Build a real-topology workspace (echo) under the build lock.

        Serialized because ``run_workspace`` drives ``runtime.generate_*`` against
        the process-global store; constructing the ``Glimi`` re-points that global
        to this workspace's store, so only one build may be in flight at a time.
        Echo keeps each build instant + deterministic.
        """
        owner_name = (name or "Owner").strip() or "Owner"
        goal = (goal or "").strip() or "Plan the public launch of our open-source project"
        with self._lock:
            g = Glimi(backend="echo", owner_name=owner_name)
            for aid, disp, atype, persona in TEAM:
                g.add_agent(aid, name=disp, persona=persona, agent_type=atype)
            # Real interaction topology (echo) → a genuine interaction web for goal.
            run_workspace(g, owner_name, goal)
            ws_id = self._next_user_id()
            ws = Workspace(id=ws_id, glimi=g, title=goal, goal=goal, kind="user")
            self.register(ws)
        return ws


# ── per-workspace dashboard endpoint shapes (mirror glimi/dashboard/app.py) ───

def _snapshot_payload(reader: DashboardReader) -> dict:
    """The exact ``/api/snapshot`` shape: snapshot + owner identity enrichment."""
    snap = reader.snapshot()
    owner_name, owner_ids = _owner_info(reader)
    snap["owner_name"] = owner_name
    snap["owner_ids"] = owner_ids
    return snap


def _index_html_for(ws: Workspace) -> str:
    """The Core dashboard index.html with per-workspace body attributes injected.

    Reads (never modifies) ``glimi/dashboard/templates/index.html``, sets
    ``<body data-api-base="/w/{id}" data-refresh-ms="6000">`` so the SAME shipped
    JS drives this workspace's endpoints, and retitles the page. One additive JS
    change (``API_BASE`` off ``data-api-base``) makes this work; without the
    attribute the standalone dashboard is unchanged.
    """
    html = _DASH_INDEX.read_text(encoding="utf-8")
    base = f"/w/{ws.id}"
    html = html.replace(
        "<body>",
        f'<body data-api-base="{base}" data-refresh-ms="6000">',
        1,
    )
    # Retitle (best-effort; both occurrences are the same string).
    html = html.replace(
        "<title>Glimi Core — Dashboard</title>",
        f"<title>{_esc(ws.title)} — Glimi Workspace</title>",
        1,
    )
    return html


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ── chat read-APIs (per-workspace) — mirror src/platform/routers/chat.py shapes ─
#
# These are the EXACT JSON contracts the copied chat.js expects, rebuilt on the
# kernel store (store-explicit reads → safe for N workspaces in parallel) with NO
# `src` import. The store rows carry only id/channel/speaker/message/... — the
# display fields (display_name / is_user) the client needs are computed HERE (the
# Workspace layer), never pushed into the kernel store.

def _chat_owner(reader: DashboardReader) -> tuple[str, set[str]]:
    """(owner display name, set of owner ids) for is_user / display resolution."""
    name, ids = _owner_info(reader)
    return name, set(ids)


def _agent_name_map(reader: DashboardReader) -> dict[str, str]:
    """``agent_id → display name`` for every agent (resolves message speakers)."""
    return {a["id"]: (a.get("name") or a["id"]) for a in reader.agents()}


def _last_preview(store, channel: str, owner_ids: set[str],
                  names: dict[str, str], owner_name: str) -> Optional[dict]:
    """The channel's most recent message as a sidebar preview, or None.

    Shape matches chat.js's ``updateChannelPreviewFromHistory`` reader:
    ``{display_name, is_user, text, timestamp}``.
    """
    try:
        recent = store.get_recent_messages(channel, 1)
    except Exception:
        return None
    if not recent:
        return None
    r = recent[-1]
    speaker = r.get("speaker") or ""
    is_user = speaker in owner_ids
    disp = owner_name if is_user else (names.get(speaker) or speaker)
    return {
        "display_name": disp,
        "is_user": is_user,
        "text": (r.get("message") or "")[:120],
        "timestamp": r.get("timestamp") or "",
    }


def _list_chat_channels(ws: "Workspace") -> list[dict]:
    """The workspace's chat channels: a DM per agent (synthesized ``dm-<id>``,
    ordered mgr/coordinator-ish first via ``reader.agents()``) plus the registered
    ``group-*`` channels. Mirrors ``chat.py._list_postable_channels``.
    """
    reader = ws.reader()
    store = ws.store
    owner_name, owner_ids = _chat_owner(reader)
    names = _agent_name_map(reader)

    out: list[dict] = []
    # DM-per-agent. reader.agents() is already mgr → creator → dev → persona → id.
    for a in reader.agents():
        aid = a.get("id")
        if not aid:
            continue
        dm_channel = f"dm-{aid}"
        out.append({
            "channel": dm_channel,
            "kind": "dm",
            "agent_id": aid,
            "name": a.get("name") or aid,
            "type": a.get("type", ""),
            "avatar_url": f"/w/{ws.id}/api/avatar?id={aid}",
            "last": _last_preview(store, dm_channel, owner_ids, names, owner_name),
        })
    # Registered group channels (multi-agent). The overview lists every channel;
    # keep only ``group-*`` (mgr-/internal-/dm- are excluded by the prefix filter).
    try:
        overview = store.get_channel_overview()
    except Exception:
        overview = []
    for c in overview:
        name = c.get("channel") or ""
        if not name.startswith("group-"):
            continue
        out.append({
            "channel": name,
            "kind": "group",
            "agent_id": None,
            "name": name,
            "type": "group",
            "avatar_url": None,
            "last": _last_preview(store, name, owner_ids, names, owner_name),
        })
    return out


def _chat_history(ws: "Workspace", channel: str, limit: int) -> list[dict]:
    """Recent messages for ``channel`` (ASC by id), display-ready. Mirrors
    ``chat.py._channel_history``: resolves speaker → display name + is_user,
    passes the store's compact ``reactions`` summary through, and resolves a
    reply quote from the loaded window when the parent is present.
    """
    reader = ws.reader()
    store = ws.store
    owner_name, owner_ids = _chat_owner(reader)
    names = _agent_name_map(reader)

    try:
        rows = store.get_recent_messages(channel, limit)
    except Exception:
        rows = []
    # get_recent_messages already returns oldest→newest within the window; sort by
    # id to be explicit (ASC) so the client renders in order.
    rows = sorted(rows, key=lambda r: (r.get("id") or 0))
    by_id = {r.get("id"): r for r in rows if r.get("id") is not None}

    def _disp(speaker: str) -> tuple[str, bool]:
        is_user = speaker in owner_ids
        return (owner_name if is_user else (names.get(speaker) or speaker)), is_user

    out: list[dict] = []
    for r in rows:
        speaker = r.get("speaker") or ""
        disp, is_user = _disp(speaker)
        # Resolve the reply quote from the loaded window (else a bare pointer).
        reply_to = None
        parent_id = r.get("reply_to")
        if parent_id is not None:
            parent = by_id.get(parent_id)
            if parent is not None:
                p_speaker = parent.get("speaker") or ""
                p_disp, p_is_user = _disp(p_speaker)
                reply_to = {
                    "id": parent_id,
                    "author": p_disp,
                    "author_id": p_speaker,
                    "is_user": p_is_user,
                    "preview": (parent.get("message") or "")[:120],
                }
            else:
                reply_to = {"id": parent_id}
        out.append({
            "id": r.get("id"),
            "speaker_id": speaker,
            "display_name": disp,
            "is_user": is_user,
            "text": r.get("message") or "",
            "timestamp": r.get("timestamp") or "",
            # The store's _summarize_reactions already yields {emoji,count,actors}.
            "reactions": r.get("reactions") or [],
            "reply_to": reply_to,
            "thread_root": r.get("thread_root"),
            "images": [],  # not modeled in the kernel store — stable client shape
        })
    return out


def _ws_dashboard_html_for(ws: "Workspace") -> str:
    """Render the Community-style workspace page (chat primary view).

    The Workspace server does not run Jinja; the template + chat-shell partial use
    literal ``{{...}}`` placeholders filled here by ``str.replace`` (same pattern
    as ``_index_html_for``). Injects the per-workspace base, owner name, and the
    read-only flag (the Demo is read-only — composer locked + banner).
    """
    reader = ws.reader()
    owner_name, _ = _chat_owner(reader)
    owner_initial = (owner_name.strip()[:1].upper() or "Y") if owner_name else "Y"
    base = f"/w/{ws.id}"
    # The Demo workspace is browse-only; user-created ones are too (echo, no live
    # turn loop here) — treat every workspace chat as read-only (it's a demo).
    readonly = "true"

    shell = _CHAT_SHELL_HTML.read_text(encoding="utf-8")
    shell = (shell
             .replace("{{ws_name}}", _esc(ws.title))
             .replace("{{owner_name}}", _esc(owner_name))
             .replace("{{owner_initial}}", _esc(owner_initial))
             .replace("{{channel}}", "dm-coordinator"))

    html = _WS_DASH_HTML.read_text(encoding="utf-8")
    html = (html
            .replace("<!--CHAT_SHELL-->", shell)
            .replace("{{ws_title}}", _esc(ws.title))
            .replace("{{ws_base}}", base)
            .replace("{{owner_name}}", _esc(owner_name))
            .replace("{{readonly}}", readonly))
    # Cache-bust the chat JS/CSS so a returning visitor never gets a stale copy.
    # chat.js/chat.css are the canonical /static (kernel) assets; tokens.css is
    # the workspace-local /wstatic one.
    for _a in ("/static/js/chat.js", "/static/css/chat.css", "/wstatic/css/tokens.css"):
        html = html.replace(_a, f"{_a}?v={_ASSET_VER}")
    return html


# ── app ───────────────────────────────────────────────────────────────────────

def create_app(registry: Optional[WorkspaceRegistry] = None,
               *, with_demo: bool = True,
               demo_interval: float = 6.0) -> FastAPI:
    """Build the multi-workspace FastAPI app.

    Registers the Demo workspace (unless ``with_demo`` is False — tests use that
    to exercise an empty registry) and starts its live activity loop on a daemon
    thread. The server owns serving; the demo loop only mutates its own store.
    """
    reg = registry or WorkspaceRegistry()
    app = FastAPI(title="Glimi Workspace — Server", docs_url=None, redoc_url=None)
    app.state.registry = reg

    # Reuse the Core dashboard's static assets (CSS/JS) for BOTH the home page and
    # every per-workspace dashboard.
    app.mount("/static", StaticFiles(directory=str(_DASH_STATIC)), name="static")
    # This app's OWN static (chat.css / chat.js / tokens.css) under a separate
    # prefix so the chat assets never collide with the kernel `/static`.
    app.mount("/wstatic", StaticFiles(directory=str(_WS_STATIC)), name="wstatic")

    if with_demo:
        _install_demo(reg, interval=demo_interval)

    def _require(ws_id: str) -> Workspace:
        ws = reg.get(ws_id)
        if ws is None:
            raise HTTPException(status_code=404, detail=f"unknown workspace: {ws_id}")
        return ws

    # ── home ──────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def home() -> FileResponse:
        return FileResponse(str(_HOME_HTML), media_type="text/html")

    @app.get("/api/workspaces")
    def list_workspaces() -> JSONResponse:
        return JSONResponse(reg.cards())

    @app.post("/api/workspaces", response_model=None)
    async def create_workspace(request: Request):
        """Create a workspace from a form (browser) or JSON (API).

        Serialized by the registry's build lock (global-singleton WRITE path).
        Form submits get a 303 redirect to the new dashboard; JSON callers get
        ``{id, title, goal, kind, ...}``.
        """
        name = goal = ""
        is_form = False
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                body = await request.json()
            except Exception:
                body = {}
            name = str(body.get("name", "") or "")
            goal = str(body.get("goal", "") or "")
        else:
            is_form = True
            form = await request.form()
            name = str(form.get("name", "") or "")
            goal = str(form.get("goal", "") or "")
        ws = reg.create(name, goal)
        if is_form:
            return RedirectResponse(url=f"/w/{ws.id}", status_code=303)
        return JSONResponse(ws.card())

    # ── per-workspace dashboard ─────────────────────────────────────────────
    # Primary view = the Community-style chat (chat shell + sidebar/feed). The
    # connection graph (the previous /w/{id} Core dashboard) moves to /w/{id}/graph
    # and is reachable from the chat page's Overview nav.
    @app.get("/w/{ws_id}", response_class=HTMLResponse)
    def dashboard(ws_id: str) -> HTMLResponse:
        ws = _require(ws_id)
        return HTMLResponse(_ws_dashboard_html_for(ws))

    @app.get("/w/{ws_id}/graph", response_class=HTMLResponse)
    def dashboard_graph(ws_id: str) -> HTMLResponse:
        """The Core connection-graph dashboard (unchanged), under /graph."""
        ws = _require(ws_id)
        return HTMLResponse(_index_html_for(ws))

    # ── per-workspace chat read-APIs (mirror the Community chat contract) ────
    @app.get("/w/{ws_id}/chat/channels")
    def w_chat_channels(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse({"channels": _list_chat_channels(ws)})

    @app.get("/w/{ws_id}/chat/history")
    def w_chat_history(ws_id: str, channel: str = "", limit: int = 50) -> JSONResponse:
        ws = _require(ws_id)
        channel = (channel or "").strip()
        if not channel:
            return JSONResponse({"error": "missing channel"}, status_code=400)
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50
        return JSONResponse({
            "channel": channel,
            "messages": _chat_history(ws, channel, limit),
        })

    @app.websocket("/w/{ws_id}/chat/ws")
    async def w_chat_ws(websocket: WebSocket, ws_id: str) -> None:
        """Read-only demo socket: accept + keep open so chat.js shows "Connected".

        No sending in the Workspace demo — we drain inbound frames (the client
        pings on connect/channel-switch) and reply 'pong' to a ping, otherwise
        ignore. Never writes to the store; never crashes on a closed socket.
        """
        if reg.get(ws_id) is None:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                frame = await websocket.receive_json()
                if (frame or {}).get("type") == "ping":
                    # Mirror the client's ping so its status flips to Connected.
                    await websocket.send_json({"type": "pong"})
                # All other inbound frames are ignored (read-only demo).
        except WebSocketDisconnect:
            pass
        except Exception:
            # Malformed frame / client gone — close quietly, never crash.
            pass

    # ── per-workspace chat avatars (workspace layer; no kernel image field) ──
    @app.get("/w/{ws_id}/api/avatar")
    def w_avatar(ws_id: str, id: str = "") -> Response:
        """Role-based monogram avatar (inline SVG). The workspace team is
        functional (Coordinator/Researcher/Builder/Critic) — no persona/anime
        portraits here. Always 200."""
        _require(ws_id)
        return Response(content=_avatar_svg(id), media_type="image/svg+xml",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/w/{ws_id}/api/snapshot")
    def w_snapshot(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse(_snapshot_payload(ws.reader()))

    @app.get("/w/{ws_id}/api/agent_detail")
    def w_agent_detail(ws_id: str, id: str) -> JSONResponse:
        ws = _require(ws_id)
        if not id:
            raise HTTPException(status_code=422, detail="id required")
        return JSONResponse(ws.reader().agent_detail(id))

    @app.get("/w/{ws_id}/api/channel")
    def w_channel(ws_id: str, name: str) -> JSONResponse:
        ws = _require(ws_id)
        if not name:
            raise HTTPException(status_code=422, detail="name required")
        return JSONResponse(_channel_detail(ws.reader(), name))

    @app.get("/w/{ws_id}/api/tool_timeline")
    def w_tool_timeline(ws_id: str, limit: int = 50) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse(ws.reader().tool_timeline(limit=limit))

    @app.get("/w/{ws_id}/api/usage")
    def w_usage(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse(ws.reader().usage())

    return app


def _install_demo(reg: WorkspaceRegistry, *, interval: float = 6.0) -> Workspace:
    """Register the Demo workspace and start its live activity loop (daemon).

    Mirrors ``demo.run_demo`` WITHOUT the blocking serve — the server owns
    serving. The loop only mutates the demo's own store (no ``runtime.generate_*``),
    so it runs safely alongside reads + serialized creates.
    """
    g = _demo.build()
    ws = Workspace(id="demo", glimi=g, title="Launch demo",
                   goal=_demo.GOAL, kind="demo")
    reg.register(ws)
    stop = threading.Event()
    thread = threading.Thread(
        target=_demo.activity_loop, args=(g, stop, interval), daemon=True,
        name="glimi-workspace-server-demo",
    )
    thread.start()
    # Daemon thread → dies with the process; server lifetime == demo lifetime, so
    # we don't expose a stop handle.
    return ws


def serve(host: str = "127.0.0.1", port: int = 8800, **uvicorn_kwargs) -> int:
    """Run the multi-workspace server (blocking). Needs ``glimi[dashboard]``."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - import-guard message
        print(f"Dashboard deps not installed: {exc}")
        print('Install with:  pip install "glimi[dashboard]"')
        return 1

    app = create_app()
    url = f"http://{host}:{port}"
    print("=" * 64)
    print("  Glimi Workspace — SERVER (N workspaces)")
    print("=" * 64)
    print(f"  home : {url}            ← workspace list + create")
    print(f"  demo : {url}/w/demo     ← seeded live demo (read-only, $0)")
    print("=" * 64 + "\n")
    uvicorn.run(app, host=host, port=port, **uvicorn_kwargs)
    return 0
