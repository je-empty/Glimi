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

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

_STORE_PATH = (os.environ.get("GLIMI_INVITES_STORE") or "").strip()
_ADMIN_PW = (os.environ.get("GLIMI_ADMIN_PASSWORD") or "").strip()
# First-run web setup: when no env password is set, the owner sets one in the
# browser (POST /admin/setup) and it's stored — pbkdf2-hashed — at GLIMI_ADMIN_PW_FILE.
# So the admin can be enabled with zero SSH.
_ADMIN_PW_FILE = (os.environ.get("GLIMI_ADMIN_PW_FILE") or "").strip()
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

def _read_file_pw() -> str:
    if not _ADMIN_PW_FILE:
        return ""
    try:
        with open(_ADMIN_PW_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _hash_pw(pw: str, salt: str = "") -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${h}"


def admin_enabled() -> bool:
    """The /admin route is reachable when a password is set OR a setup-file path is
    configured (so first-run web setup can run). None of these → /admin is off."""
    return bool(_ADMIN_PW) or bool(_ADMIN_PW_FILE) or bool(_read_file_pw())


def needs_setup() -> bool:
    """No password configured yet → show the first-run 'set a password' form."""
    return not _ADMIN_PW and not _read_file_pw()


def set_password(pw: str) -> bool:
    """First-run only: store a pbkdf2-hashed password to the file. Refuses if a
    password already exists (no web takeover) or no file path is configured."""
    pw = (pw or "").strip()
    if len(pw) < 6 or not needs_setup() or not _ADMIN_PW_FILE:
        return False
    tmp = _ADMIN_PW_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_hash_pw(pw))
    os.replace(tmp, _ADMIN_PW_FILE)
    return True


def check_password(pw: str) -> bool:
    pw = (pw or "").strip()
    if not pw:
        return False
    if _ADMIN_PW and hmac.compare_digest(pw, _ADMIN_PW):
        return True
    stored = _read_file_pw()
    if stored and "$" in stored:
        salt, h = stored.split("$", 1)
        try:
            calc = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                                       bytes.fromhex(salt), 200_000).hex()
            return hmac.compare_digest(calc, h)
        except (ValueError, TypeError):
            return False
    return False


def _secret() -> str:
    """Cookie-signing secret (read live): a dedicated env, else the password material
    (env or stored hash) — so changing the password invalidates old sessions."""
    return (os.environ.get("GLIMI_ADMIN_SECRET") or _ADMIN_PW or _read_file_pw()
            or "glimi-admin-dev").strip()


def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(_secret(), salt="glimi-admin-session")


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
