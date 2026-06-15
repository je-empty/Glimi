"""FastAPI web app for the store-driven Glimi Core dashboard (P1.1).

This is the **web layer** of the ``glimi[dashboard]`` extra. It is intentionally
isolated from the zero-dep base: FastAPI / uvicorn / Jinja are imported *here*, at
module top level, so importing this module requires the extra. The reader
(:mod:`glimi.dashboard.reader`) stays importable with zero dependencies; the
``serve`` entry point in :mod:`glimi.dashboard` lazy-imports this module only when
you actually start the server.

Scope — **read-only**. The app exposes exactly three data endpoints backed by
:class:`~glimi.dashboard.reader.DashboardReader`, plus static asset serving:

- ``GET /``                      → the dashboard HTML (client-rendered).
- ``GET /api/snapshot``          → graph + KPIs (agents / channels / relationships).
- ``GET /api/agent_detail?id=``  → one agent's profile + 5-layer memory + facts +
  relationships.
- ``GET /api/channel?name=``     → a channel's participants + messages.

There are **no** mutation endpoints, **no** Discord / sync / scan, **no**
supervisor or server start/stop, **no** community switcher, **no** auth. Panels
the kernel store cannot back (health / usage / logs / achievements / dev-requests
/ model catalog) are simply not present in this read-only slice.

Design constraints (mirrors the reader): domain-neutral (no ``dm-`` / ``mgr-``
channel-name special-casing, no hardcoded community content), and best-effort —
the store contract says reads should not raise, but the endpoints still degrade to
empty data rather than 500 on a sparse store.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .reader import DashboardReader

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATES_DIR = _HERE / "templates"
_INDEX_HTML = _TEMPLATES_DIR / "index.html"


def create_app(reader: DashboardReader) -> FastAPI:
    """Build the read-only dashboard FastAPI app for a given reader.

    Args:
        reader: a :class:`~glimi.dashboard.reader.DashboardReader` wrapping the
            store whose population you want to view. (Use :func:`serve` if you
            have a raw store — it constructs the reader for you.)
    """
    if not isinstance(reader, DashboardReader):
        raise TypeError("create_app expects a DashboardReader instance")

    app = FastAPI(title="Glimi Core — Dashboard", docs_url=None, redoc_url=None)

    # Static assets (css / js). Mounted under /static — the template links there.
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        """The dashboard page. Fully client-rendered; fetches the API below."""
        return FileResponse(str(_INDEX_HTML), media_type="text/html")

    @app.get("/api/snapshot")
    def api_snapshot() -> JSONResponse:
        """Graph snapshot: agents + channels + relationships.

        Enriched with owner identity (``owner_name`` / ``owner_ids``) so the
        client can label the owner node and tag owner-authored messages without
        guessing — the reader itself stays population-only, so we read users here.
        """
        snap = reader.snapshot()
        owner_name, owner_ids = _owner_info(reader)
        snap["owner_name"] = owner_name
        snap["owner_ids"] = owner_ids
        return JSONResponse(snap)

    @app.get("/api/agent_detail")
    def api_agent_detail(id: str = Query(..., min_length=1)) -> JSONResponse:
        """One agent: profile + 5-layer memory + pinned + facts + relationships."""
        return JSONResponse(reader.agent_detail(id))

    @app.get("/api/channel")
    def api_channel(name: str = Query(..., min_length=1)) -> JSONResponse:
        """One channel: participants + recent messages (oldest → newest).

        ``DashboardReader`` summarizes channels but does not return per-message
        bodies, so this endpoint reads messages straight off the store (read-only)
        and shapes them like the agent's channel viewer expects.
        """
        return JSONResponse(_channel_detail(reader, name))

    return app


# ── helpers (read-only store reads the reader does not surface) ───────────

def _owner_info(reader: DashboardReader) -> tuple[str, list[str]]:
    """(display name, list of user ids) for the registered owner(s).

    Best-effort: returns ``("Owner", [])`` if the store exposes no users. The
    first registered user is treated as the display owner; all user ids are
    returned so the client can distinguish owner-authored messages from agents.
    """
    try:
        users = reader.store.list_users() or []
    except Exception:
        users = []
    ids = [u.get("id") for u in users if u.get("id")]
    name = "Owner"
    if users:
        name = users[0].get("name") or users[0].get("id") or "Owner"
    return name, ids


def _channel_detail(reader: DashboardReader, name: str) -> dict:
    """Participants + messages for a channel, read straight off the store.

    Domain-neutral and best-effort. Messages come from
    ``store.get_recent_messages`` (the kernel conversation log); participants from
    ``store.get_channel_participants``.
    """
    store = reader.store
    try:
        participants = store.get_channel_participants(name) or []
    except Exception:
        participants = []
    try:
        messages = store.get_recent_messages(name, limit=300) or []
    except Exception:
        messages = []
    return {
        "name": name,
        "participants": participants,
        "messages": messages,
        "message_count": len(messages),
    }


def create_app_for_store(store) -> FastAPI:
    """Convenience: build the app directly from a store (wraps it in a reader)."""
    return create_app(DashboardReader(store))
