# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""glimi.dashboard.invites — shared invite-token store + admin-password storage.

One store, three apps: the **landing** admin (glimi.iruyo.com/admin) issues tokens;
the **community** and **workspace** apps gate their chat-enabled "presenter" demos
on them. Each token carries a ``target`` (``community`` | ``workspace``) so one
panel manages both. Stdlib only (no fastapi/itsdangerous) → importing
``glimi.dashboard`` stays dependency-free; the web session signing lives in the app.

Paths come from env, read LIVE per call so the owner can issue/revoke with no restart:
  GLIMI_INVITES_STORE   — tokens JSON (list of {token,label,kind,target,created,last_used,uses})
  GLIMI_ADMIN_PW_FILE   — pbkdf2 password hash (first-run web setup writes it)
  GLIMI_ADMIN_PASSWORD  — alternative static admin password (env)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone

TARGETS = ("community", "workspace")


def _store_path() -> str:
    return (os.environ.get("GLIMI_INVITES_STORE") or "").strip()


def _pw_file() -> str:
    return (os.environ.get("GLIMI_ADMIN_PW_FILE") or "").strip()


def _env_pw() -> str:
    return (os.environ.get("GLIMI_ADMIN_PASSWORD") or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── token store (JSON, live, atomic) ─────────────────────────────────────────

def _load() -> list:
    p = _store_path()
    if not p:
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list) -> None:
    p = _store_path()
    if not p:
        return
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def list_tokens(target: str = "") -> list:
    """Issued tokens (newest first), optionally filtered to one target."""
    items = sorted(_load(), key=lambda it: it.get("created", ""), reverse=True)
    return [it for it in items if not target or it.get("target") == target]


def token_set(target: str = "") -> set:
    """Valid token strings, optionally only those for ``target`` (for a gate)."""
    return {it["token"] for it in _load()
            if it.get("token") and (not target or it.get("target") == target)}


def issue(label: str, kind: str, target: str) -> dict:
    items = _load()
    item = {
        "token": secrets.token_urlsafe(9),
        "label": (label or "").strip()[:80] or "(이름 없음)",
        "kind": kind if kind in ("continue", "fresh") else "continue",
        "target": target if target in TARGETS else "workspace",
        "created": _now(),
        "last_used": None,
        "uses": 0,
    }
    items.append(item)
    _save(items)
    return item


def revoke(token: str) -> bool:
    items = _load()
    kept = [it for it in items if it.get("token") != token]
    if len(kept) != len(items):
        _save(kept)
        return True
    return False


def touch(token: str) -> None:
    """Record a use (last_used + count). Best-effort; never raises into a request."""
    if not _store_path() or not token:
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


# ── admin password (pbkdf2, stdlib; first-run web setup) ─────────────────────

def _read_file_pw() -> str:
    p = _pw_file()
    if not p:
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _hash_pw(pw: str, salt: str = "") -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${h}"


def admin_enabled() -> bool:
    """The /admin route is reachable once a password is set OR a setup-file path is
    configured (so first-run web setup can run)."""
    return bool(_env_pw()) or bool(_pw_file()) or bool(_read_file_pw())


def needs_setup() -> bool:
    """No password configured yet → show the first-run 'set a password' form."""
    return not _env_pw() and not _read_file_pw()


def set_password(pw: str) -> bool:
    """First-run only: store a pbkdf2 hash to the file. Refused once a password
    exists (no web takeover) or if no file path is configured."""
    pw = (pw or "").strip()
    if len(pw) < 6 or not needs_setup() or not _pw_file():
        return False
    tmp = _pw_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_hash_pw(pw))
    os.replace(tmp, _pw_file())
    return True


def check_password(pw: str) -> bool:
    pw = (pw or "").strip()
    if not pw:
        return False
    env = _env_pw()
    if env and hmac.compare_digest(pw, env):
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


def admin_secret() -> str:
    """Material for the app's session-cookie signing (read live): a dedicated env,
    else the password material — so changing the password invalidates old sessions."""
    return (os.environ.get("GLIMI_ADMIN_SECRET") or _env_pw() or _read_file_pw()
            or "glimi-admin-dev").strip()
