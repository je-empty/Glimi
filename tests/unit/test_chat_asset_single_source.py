"""Dashboard front-end single-source guard.

The rich dashboard — its assets (``dashboard.js`` / ``dashboard.css`` /
``dashboard-chat.css`` / ``base.css`` / ``tokens.css`` + the chat client
``chat.js`` / ``chat.css``), its templates (``dashboard/_core.html`` +
``_chat_shell.html``) and its i18n dicts — is **canonical in the kernel dashboard**
(``glimi/dashboard``) and shipped with ``glimi[dashboard]``. Both apps consume that
one source:

  - **Workspace** renders the canonical templates + serves the canonical ``/static``
    straight from the installed package and keeps **NO copy** of its own.
  - **Community** serves the assets from its existing ``/static`` URL (the
    service-worker / cache-busting machinery hangs off that path), so it keeps a
    **byte-identical synced copy** — the content is the canonical, the URL is
    unchanged. (Community's dashboard *template* migration to the canonical shell
    is a separate, live-verified step; until then it keeps its own template that
    loads these canonical assets.)

This test fails the moment a copy drifts, so a change to the dashboard can't
silently fork again — edit the canonical in ``glimi/dashboard``, then re-sync the
community copies:

    cp glimi/dashboard/static/js/dashboard.js   community/platform/static/js/dashboard.js
    cp glimi/dashboard/static/css/dashboard.css community/platform/static/css/dashboard.css
    cp glimi/dashboard/i18n/dashboard.*.json    i18n/

Run:
    python -m pytest tests/unit/test_chat_asset_single_source.py -q
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(p: str) -> str:
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# Canonical (glimi/dashboard) → Community synced copy.
#   static assets live under static/; i18n dicts under i18n/ (community keeps its
#   copy at the repo-root i18n/ that its /api/i18n endpoint reads).
_SYNCED = [
    ("static/js/chat.js",            "community/platform/static/js/chat.js"),
    ("static/css/chat.css",          "community/platform/static/css/chat.css"),
    ("static/js/dashboard.js",       "community/platform/static/js/dashboard.js"),
    ("static/css/dashboard.css",     "community/platform/static/css/dashboard.css"),
    ("static/css/dashboard-chat.css", "community/platform/static/css/dashboard-chat.css"),
    ("static/css/base.css",          "community/platform/static/css/base.css"),
    ("static/css/tokens.css",        "community/platform/static/css/tokens.css"),
    ("i18n/dashboard.en.json",       "i18n/dashboard.en.json"),
    ("i18n/dashboard.ko.json",       "i18n/dashboard.ko.json"),
]


def test_community_assets_match_canonical():
    for rel, comm_rel in _SYNCED:
        canon = os.path.join(_ROOT, "glimi", "dashboard", rel)
        comm = os.path.join(_ROOT, comm_rel)
        assert os.path.exists(canon), f"canonical missing: glimi/dashboard/{rel}"
        assert os.path.exists(comm), f"community copy missing: {comm_rel}"
        assert _read(comm) == _read(canon), (
            f"community {comm_rel} drifted from the canonical — re-sync:\n"
            f"  cp glimi/dashboard/{rel} {comm_rel}"
        )


def test_workspace_keeps_no_asset_copies():
    # The workspace consumes the canonical from the package — it must not vendor
    # its own dashboard/chat assets (no workspace/static at all).
    ws_static = os.path.join(_ROOT, "workspace", "static")
    assert not os.path.isdir(ws_static), (
        "workspace/static should not exist — the workspace serves the "
        "canonical assets from /static (glimi/dashboard) via the package."
    )
    ws_i18n = os.path.join(_ROOT, "workspace", "i18n")
    assert not os.path.isdir(ws_i18n), (
        "workspace/i18n should not exist — the workspace loads the canonical "
        "i18n dicts from glimi/dashboard/i18n via the package."
    )


def test_canonical_templates_present():
    # The shared shell + chat partial must ship from the kernel package.
    for rel in ("templates/dashboard/_core.html", "templates/_chat_shell.html"):
        p = os.path.join(_ROOT, "glimi", "dashboard", rel)
        assert os.path.exists(p), f"canonical template missing: glimi/dashboard/{rel}"


def test_workspace_keeps_no_dashboard_template_copy():
    # The workspace renders the canonical dashboard/_core.html AND the shared
    # _demo_list.html home — it must not fork its own copies of these.
    for stray in ("dashboard/_core.html", "dashboard/index.html", "base.html", "_chat_shell.html"):
        p = os.path.join(_ROOT, "workspace", "templates", stray)
        assert not os.path.exists(p), (
            f"workspace/templates/{stray} should not exist — the workspace "
            "renders the canonical shell from glimi/dashboard/templates."
        )
