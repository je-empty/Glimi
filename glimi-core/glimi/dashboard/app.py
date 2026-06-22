# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
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
- ``GET /api/tool_timeline``     → recent tool-call invocations (name / args /
  result / latency / ok).
- ``GET /api/usage``             → LLM usage/cost view (today + month-to-date spend,
  call count, avg latency; CLI rows flagged estimated).

There are **no** mutation endpoints, **no** Discord / sync / scan, **no**
supervisor or server start/stop, **no** community switcher, **no** auth. Panels
the kernel store cannot back (health / logs / achievements / dev-requests / model
catalog) are simply not present in this read-only slice. Tool-call and usage
panels *are* store-backed and therefore present.

Design constraints (mirrors the reader): domain-neutral (no ``dm-`` / ``mgr-``
channel-name special-casing, no hardcoded community content), and best-effort —
the store contract says reads should not raise, but the endpoints still degrade to
empty data rather than 500 on a sparse store.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .reader import DashboardReader
# owner_info/channel_detail/enrich_snapshot are public, pure helpers in reader
# (zero-dep) so apps can import them from glimi.dashboard without the web layer.
# Keep the underscore aliases for this module's internal callers (back-compat).
from .reader import (
    owner_info as _owner_info,
    channel_detail as _channel_detail,
    enrich_snapshot as _enrich_snapshot,
)

_HERE = Path(__file__).resolve().parent
_STATIC_DIR = _HERE / "static"
_TEMPLATES_DIR = _HERE / "templates"
_I18N_DIR = _HERE / "i18n"

# The rich, config-driven dashboard shell — the single canonical template, shared
# with Glimi Workspace / Community. Rendered here for the kernel's own demo with a
# kernel-default context (no community chrome; the chat-less store viewer opens on
# Overview). Jinja is imported at module top (web-layer only) — `import
# glimi.dashboard` stays zero-dep because this module is lazy-imported by serve().
_TEMPLATES = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Capabilities the kernel store can actually back. Everything else (chat backend,
# scenes / achievements / supervisors / sync / events / health / logs) is an app
# concern → off, so those tabs hide and the viewer opens on Overview.
_KERNEL_CAPS = {
    "chat": False, "scenes": False, "achievements": False, "supervisors": False,
    "sync": False, "events": False, "health": False, "logs": False,
}


def _load_i18n(lang: str) -> dict:
    lang = (lang or "en").lower()
    if lang not in ("ko", "en"):
        lang = "en"
    try:
        with open(_I18N_DIR / f"dashboard.{lang}.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # best-effort: a missing dict must not 500 the page
        return {"error": str(exc)}


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
    def index(request: Request):
        """The dashboard page (rich shell, client-rendered; fetches the API below).

        Rendered from the canonical ``dashboard/_core.html`` with a kernel-default
        context: no community chrome, kernel-only caps, opens on Overview (the
        read-only store viewer has no chat backend)."""
        lang = (request.query_params.get("lang") or "en").lower()
        if lang not in ("ko", "en"):
            lang = "en"
        ctx = {
            "request": request,
            "static_base": "/static",
            "api_base": "",
            "caps_json": json.dumps(_KERNEL_CAPS),
            "community_chrome": False,
            "app_name": "Glimi Core",
            "active_tab": "overview",
            "user": None,
            "community_id": None,
            "community_name": "Glimi Core",
            "language": lang,
            "read_only": True,
            "asset_v": "1",
            "chat_channel": None,
            "chat_agent": None,
            "chat_user": "You",
        }
        return _TEMPLATES.TemplateResponse(request, "dashboard/_core.html", ctx)

    @app.get("/api/snapshot")
    def api_snapshot() -> JSONResponse:
        """Graph snapshot in the rich dashboard shape: agents (+ live flags /
        presentation defaults) + channels (+ kind/participant_count) + relationships
        + aggregated ``recent_messages`` + ``meta`` / ``bot`` / ``total_messages``.
        See :func:`glimi.dashboard.enrich_snapshot`."""
        return JSONResponse(_enrich_snapshot(reader))

    @app.get("/api/i18n")
    def api_i18n(lang: str = "en") -> JSONResponse:
        """Dashboard chrome translations for the KO/EN picker (shipped dicts)."""
        return JSONResponse(_load_i18n(lang))

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

    @app.get("/api/tool_timeline")
    def api_tool_timeline(limit: int = 50) -> JSONResponse:
        """Recent tool-call invocations (newest first), store-backed."""
        return JSONResponse(reader.tool_timeline(limit=limit))

    @app.get("/api/usage")
    def api_usage() -> JSONResponse:
        """LLM usage/cost view (today + month-to-date), store-backed."""
        return JSONResponse(reader.usage())

    return app


# ── helpers ───────────────────────────────────────────────────────────────
# _owner_info / _channel_detail are imported above as aliases of the now-public
# reader.owner_info / reader.channel_detail (kept zero-dep so apps can consume
# them from glimi.dashboard). The defs used to live here.


def create_app_for_store(store) -> FastAPI:
    """Convenience: build the app directly from a store (wraps it in a reader)."""
    return create_app(DashboardReader(store))
