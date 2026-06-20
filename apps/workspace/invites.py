# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""apps/workspace/invites.py — invite-token store + admin session, for the web
admin panel (/admin).

Tokens live in a JSON file (``GLIMI_INVITES_STORE``) with metadata — label, kind
(continue/fresh), created, last_used, uses — so the owner can issue, list, see
usage, and revoke from the browser instead of SSH-ing in. Read live every request
(no restart). The admin panel is gated by ``GLIMI_ADMIN_PASSWORD`` (the owner sets
it once); the session is a signed cookie (itsdangerous). All stdlib + itsdangerous;
never src / Discord.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
from datetime import datetime, timezone

_STORE_PATH = (os.environ.get("GLIMI_INVITES_STORE") or "").strip()
_ADMIN_PW = (os.environ.get("GLIMI_ADMIN_PASSWORD") or "").strip()
# Cookie-signing secret: a dedicated env, else derived from the password (changes
# if the password changes → old sessions invalidate, which is the safe default).
_SECRET = (os.environ.get("GLIMI_ADMIN_SECRET") or _ADMIN_PW or "glimi-admin-dev").strip()
_SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── token store (JSON, live, atomic writes) ──────────────────────────────────

def _load() -> list:
    if not _STORE_PATH:
        return []
    try:
        with open(_STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list) -> None:
    if not _STORE_PATH:
        return
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _STORE_PATH)  # atomic


def list_tokens() -> list:
    """All issued tokens (newest first), each a dict with metadata."""
    return sorted(_load(), key=lambda it: it.get("created", ""), reverse=True)


def token_set() -> set:
    """The set of currently-valid token strings (for the gate)."""
    return {it["token"] for it in _load() if it.get("token")}


def issue(label: str, kind: str) -> dict:
    """Mint a new token + metadata, persist, return it."""
    items = _load()
    item = {
        "token": secrets.token_urlsafe(9),
        "label": (label or "").strip()[:80] or "(이름 없음)",
        "kind": kind if kind in ("continue", "fresh") else "continue",
        "created": _now(),
        "last_used": None,
        "uses": 0,
    }
    items.append(item)
    _save(items)
    return item


def revoke(token: str) -> bool:
    """Delete a token. True if it existed."""
    items = _load()
    kept = [it for it in items if it.get("token") != token]
    if len(kept) != len(items):
        _save(kept)
        return True
    return False


def touch(token: str) -> None:
    """Record a use (last_used + count). Best-effort, never raises into the request."""
    if not _STORE_PATH or not token:
        return
    try:
        items = _load()
        hit = False
        for it in items:
            if it.get("token") == token:
                it["last_used"] = _now()
                it["uses"] = int(it.get("uses", 0)) + 1
                hit = True
        if hit:
            _save(items)
    except Exception:
        pass


# ── admin session (signed cookie) ────────────────────────────────────────────

def admin_enabled() -> bool:
    """The admin panel is active only once the owner sets GLIMI_ADMIN_PASSWORD."""
    return bool(_ADMIN_PW)


def check_password(pw: str) -> bool:
    return bool(_ADMIN_PW) and hmac.compare_digest((pw or "").strip(), _ADMIN_PW)


def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(_SECRET, salt="glimi-admin-session")


def make_session() -> str:
    return _serializer().dumps({"admin": True})


def valid_session(cookie: str) -> bool:
    if not cookie:
        return False
    try:
        from itsdangerous import BadData
    except Exception:
        return False
    try:
        self_ser = _serializer()
        self_ser.loads(cookie, max_age=_SESSION_MAX_AGE)
        return True
    except BadData:
        return False
    except Exception:
        return False
