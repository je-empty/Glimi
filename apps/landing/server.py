# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""apps/landing/server.py — the standalone Glimi landing portal.

One page: logo + copy + two links (Community demo, Workspace demo). Its own port,
so the public site is three separate services — Landing / Community / Workspace —
behind their own subdomains, each app owning its origin root (which is exactly how
an OSS adopter would run them: no landing, each app its own address). The portal
adds nothing to the apps; the link targets come from env so DEPLOYMENT decides the
routing, never the app code:

    GLIMI_COMMUNITY_URL   e.g. https://glimi-community.iruyo.com/community/demo
    GLIMI_WORKSPACE_URL   e.g. https://glimi-workspace.iruyo.com/w/demo

Both default to relative paths for local/OSS use. Stateless — no DB, no auth.

Kernel-light: imports fastapi + stdlib and reuses the canonical
``glimi.dashboard`` static (base.css → design tokens + fonts). Never src / Discord.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import glimi.dashboard as _dashboard  # canonical static (base.css/tokens) — stdlib-only import

_APP_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _APP_DIR.parent.parent                 # apps/landing → apps → repo root
_RESOURCES = _REPO_ROOT / "resources"
_DASH_STATIC = Path(_dashboard.__file__).resolve().parent / "static"
_TEMPLATES = Jinja2Templates(directory=str(_APP_DIR / "templates"))


def _asset_ver() -> str:
    """Cache-busting token = short hash of the newest canonical static mtime."""
    try:
        latest = max((p.stat().st_mtime for p in _DASH_STATIC.rglob("*") if p.is_file()),
                     default=0.0)
    except Exception:
        latest = 0.0
    return hashlib.sha1(f"{latest}".encode("utf-8")).hexdigest()[:8]


_ASSET_VER = _asset_ver()


def create_app() -> FastAPI:
    app = FastAPI(title="Glimi — Landing", docs_url=None, redoc_url=None)
    # Reuse the canonical dashboard static (base.css → tokens + fonts). Single
    # source — the portal vendors no CSS of its own.
    app.mount("/static", StaticFiles(directory=str(_DASH_STATIC)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request, lang: str = "ko"):
        """The portal. KO default (primary audience); ``?lang=en`` switches. Link
        targets are read per-request from env so routing is a deployment concern."""
        lang = "en" if (lang or "").lower() == "en" else "ko"
        community_url = (os.environ.get("GLIMI_COMMUNITY_URL") or "").strip() or "/community/demo"
        workspace_url = (os.environ.get("GLIMI_WORKSPACE_URL") or "").strip()
        # English demo variant mirrors the platform's convention (no-op if the URL
        # carries no /community/demo path, e.g. a bare subdomain).
        community_url_en = community_url.replace("/community/demo", "/community/demo-en")
        ctx = {
            "request": request, "lang": lang, "asset_v": _ASSET_VER,
            "community_url": community_url, "community_url_en": community_url_en,
            "workspace_url": workspace_url,
        }
        resp = _TEMPLATES.TemplateResponse(request, "landing.html", ctx)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/logo")
    def logo() -> Response:
        """The Glimi logo (SVG preferred, PNG fallback) from resources/ — same
        asset the other apps serve at /logo, so the portal is self-sufficient."""
        for name, mt in (("Glimi-logo.svg", "image/svg+xml"), ("Glimi-logo.png", "image/png")):
            p = _RESOURCES / name
            if p.exists():
                return Response(content=p.read_bytes(), media_type=mt,
                                headers={"Cache-Control": "public, max-age=3600"})
        return Response(status_code=404)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/admin")
    def admin_redirect() -> RedirectResponse:
        """The token-admin panel lives on the Workspace app (where the tokens are);
        redirect glimi.iruyo.com/admin → there so the front-door URL works too."""
        ws = (os.environ.get("GLIMI_WORKSPACE_URL") or "").strip()
        target = "/admin"
        if ws:
            from urllib.parse import urlsplit
            p = urlsplit(ws)
            if p.scheme and p.netloc:
                target = f"{p.scheme}://{p.netloc}/admin"
        return RedirectResponse(url=target, status_code=302)

    return app


def serve(host: str = "127.0.0.1", port: int = 8200, **uvicorn_kwargs) -> int:
    """Run the landing portal (blocking). Needs ``fastapi`` + ``uvicorn``."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - import-guard message
        print(f"Landing deps not installed: {exc}")
        print('Install with:  pip install fastapi uvicorn jinja2')
        return 1
    community = (os.environ.get("GLIMI_COMMUNITY_URL") or "/community/demo").strip()
    workspace = (os.environ.get("GLIMI_WORKSPACE_URL") or "(unset)").strip()
    url = f"http://{host}:{port}"
    print("=" * 64)
    print("  Glimi — Landing portal (entry hub)")
    print("=" * 64)
    print(f"  url       : {url}")
    print(f"  community : {community}")
    print(f"  workspace : {workspace}")
    print("=" * 64 + "\n")
    uvicorn.run(create_app(), host=host, port=port, **uvicorn_kwargs)
    return 0
