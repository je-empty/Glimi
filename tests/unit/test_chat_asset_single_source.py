"""Chat front-end single-source guard.

The chat client (``chat.js`` + ``chat.css``) is **canonical in the kernel
dashboard** (``glimi/dashboard/static``) and shipped with ``glimi[dashboard]``.
Both apps consume that one source:

  - **Workspace** mounts it directly at ``/static`` and keeps NO copy of its own.
  - **Community** serves it from its existing ``/static`` URL (service-worker /
    cache-busting machinery hangs off that path), so it keeps a **byte-identical
    synced copy** — the file content is the canonical, the URL is unchanged.

This test fails the moment the copies drift, so a change to the chat client can't
silently fork again (edit the canonical, then copy it to ``src/platform``):

    cp glimi/dashboard/static/js/chat.js  src/platform/static/js/chat.js
    cp glimi/dashboard/static/css/chat.css src/platform/static/css/chat.css

Run:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_chat_asset_single_source.py -q
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CANON_JS = os.path.join(_ROOT, "glimi", "dashboard", "static", "js", "chat.js")
_CANON_CSS = os.path.join(_ROOT, "glimi", "dashboard", "static", "css", "chat.css")
_COMM_JS = os.path.join(_ROOT, "src", "platform", "static", "js", "chat.js")
_COMM_CSS = os.path.join(_ROOT, "src", "platform", "static", "css", "chat.css")
_WS_STATIC = os.path.join(_ROOT, "apps", "workspace", "static")


def _read(p: str) -> str:
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


def test_community_chat_js_matches_canonical():
    assert os.path.exists(_CANON_JS), "canonical chat.js missing in glimi/dashboard"
    assert _read(_COMM_JS) == _read(_CANON_JS), (
        "community chat.js drifted from the canonical — re-sync:\n"
        "  cp glimi/dashboard/static/js/chat.js src/platform/static/js/chat.js"
    )


def test_community_chat_css_matches_canonical():
    assert _read(_COMM_CSS) == _read(_CANON_CSS), (
        "community chat.css drifted from the canonical — re-sync:\n"
        "  cp glimi/dashboard/static/css/chat.css src/platform/static/css/chat.css"
    )


def test_workspace_keeps_no_chat_copy():
    # Workspace must load the canonical from /static, not fork its own copy.
    for stray in ("js/chat.js", "css/chat.css"):
        p = os.path.join(_WS_STATIC, stray)
        assert not os.path.exists(p), (
            f"apps/workspace/static/{stray} should not exist — the workspace "
            "loads the canonical chat client from /static (glimi/dashboard)."
        )
