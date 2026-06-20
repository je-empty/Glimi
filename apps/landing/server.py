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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import glimi.dashboard as _dashboard  # canonical static (base.css/tokens) — stdlib-only import
from glimi.dashboard import invites as _invites  # shared token store (community + workspace)

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


# ── central admin session (the token panel; signed cookie via itsdangerous) ──
def _admin_serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(_invites.admin_secret(), salt="glimi-admin-session")


def _make_admin_session() -> str:
    return _admin_serializer().dumps({"a": 1})


def _valid_admin_session(cookie: str) -> bool:
    if not cookie:
        return False
    try:
        _admin_serializer().loads(cookie, max_age=7 * 24 * 3600)
        return True
    except Exception:
        return False


def _admin_authed(request: Request) -> bool:
    return _invites.admin_enabled() and _valid_admin_session(request.cookies.get("glimi_admin", ""))


def _origin(url: str) -> str:
    from urllib.parse import urlsplit
    p = urlsplit((url or "").strip())
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


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

    # ── central token-admin panel (community + workspace) ───────────────────
    # Hidden, password-gated. First visit (no password) → web setup. Manages the
    # shared store (glimi.dashboard.invites); each token has a target.
    @app.get("/admin", response_class=HTMLResponse)
    def admin_panel(request: Request):
        authed = _admin_authed(request)
        ctx = {
            "request": request,
            "enabled": _invites.admin_enabled(),
            "needs_setup": _invites.needs_setup(),
            "authed": authed,
            "tokens": _invites.list_tokens() if authed else [],
            "ws_base": _origin(os.environ.get("GLIMI_WORKSPACE_URL", "")),
            "community_url": (os.environ.get("GLIMI_COMMUNITY_URL") or "").strip(),
            "login_error": request.query_params.get("e") == "1",
            "setup_error": request.query_params.get("e") == "2",
        }
        resp = _TEMPLATES.TemplateResponse(request, "admin.html", ctx)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/admin/setup")
    async def admin_setup(request: Request):
        form = await request.form()
        if _invites.set_password(str(form.get("password", ""))):
            resp = RedirectResponse(url="/admin", status_code=303)
            resp.set_cookie("glimi_admin", _make_admin_session(),
                            max_age=7 * 24 * 3600, httponly=True, samesite="lax")
            return resp
        return RedirectResponse(url="/admin?e=2", status_code=303)

    @app.post("/admin/login")
    async def admin_login(request: Request):
        form = await request.form()
        if _invites.check_password(str(form.get("password", ""))):
            resp = RedirectResponse(url="/admin", status_code=303)
            resp.set_cookie("glimi_admin", _make_admin_session(),
                            max_age=7 * 24 * 3600, httponly=True, samesite="lax")
            return resp
        return RedirectResponse(url="/admin?e=1", status_code=303)

    @app.post("/admin/logout")
    def admin_logout():
        resp = RedirectResponse(url="/admin", status_code=303)
        resp.delete_cookie("glimi_admin")
        return resp

    @app.post("/admin/issue")
    async def admin_issue(request: Request):
        if not _admin_authed(request):
            raise HTTPException(status_code=403, detail="admin auth required")
        form = await request.form()
        _invites.issue(str(form.get("label", "")), str(form.get("kind", "continue")),
                       str(form.get("target", "workspace")))
        return RedirectResponse(url="/admin", status_code=303)

    @app.post("/admin/revoke")
    async def admin_revoke(request: Request):
        if not _admin_authed(request):
            raise HTTPException(status_code=403, detail="admin auth required")
        form = await request.form()
        _invites.revoke(str(form.get("token", "")))
        return RedirectResponse(url="/admin", status_code=303)

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
