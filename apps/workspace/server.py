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

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

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

# This app's own home template.
_HOME_HTML = Path(__file__).resolve().parent / "templates" / "home.html"


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

    # ── per-workspace dashboard (Core dashboard, per-id prefix) ────────────
    @app.get("/w/{ws_id}", response_class=HTMLResponse)
    def dashboard(ws_id: str) -> HTMLResponse:
        ws = _require(ws_id)
        return HTMLResponse(_index_html_for(ws))

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
