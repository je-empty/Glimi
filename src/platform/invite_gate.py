"""Community invite gate — who may enter an ``invite_required`` community (the
chat-enabled "presenter" demo, e.g. ``demo-live``).

Mirrors the workspace gate but with ``target="community"`` on the shared token
store, so the central admin (glimi.iruyo.com/admin) issues community tokens that
unlock chat here. **Scope-safe**: every helper takes a Starlette ``Request`` *or*
``WebSocket`` (both expose ``.query_params`` / ``.cookies`` / ``.headers``).

Tokens come from (live, per request):
  - ``GLIMI_INVITE_TOKENS`` env (comma-separated) — optional static tokens
  - ``glimi.dashboard.invites.token_set(target="community")`` — admin-managed JSON store
Owner = ``Cf-Access-Authenticated-User-Email`` header == ``GLIMI_OWNER_EMAIL``.
SECURITY: this header is only trustworthy when (a) the request actually traversed
Cloudflare Access (which strips/overwrites client-supplied ``Cf-Access-*``) AND
(b) the origin is NOT directly reachable (bind 127.0.0.1 behind the tunnel, never
0.0.0.0 on a shared/exposed host). If the origin is exposed, an attacker can spoof
the header → owner. Here the owner path only unlocks the demo-live presenter (a clone
of the already-public demo → cost-abuse at worst, never a private-data leak), but keep
the localhost bind. Do NOT extend this header-trust to private surfaces.

SECURITY: callers must apply this ONLY to communities where
``is_invite_required(cid)`` is true. A community token must never affect a normal
community (it would otherwise admit/unblock the owner's real communities).
"""
from __future__ import annotations

import os

INVITE_COOKIE = "glimi_invite"


def _env_tokens() -> set:
    raw = os.environ.get("GLIMI_INVITE_TOKENS", "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def community_tokens() -> set:
    """Valid community invite tokens (env ∪ admin-managed store), read live."""
    toks = _env_tokens()
    try:
        from glimi.dashboard import invites
        toks |= invites.token_set(target="community")
    except Exception:
        pass
    return toks


def request_token(scope) -> str:
    """The presented token: ``?invite=`` (first visit) or the remembered cookie."""
    try:
        q = scope.query_params.get("invite")
    except Exception:
        q = None
    c = None
    try:
        c = scope.cookies.get(INVITE_COOKIE)
    except Exception:
        c = None
    return (q or c or "").strip()


def is_owner(scope) -> bool:
    """True iff Cloudflare Access authenticated the configured owner email."""
    email = (os.environ.get("GLIMI_OWNER_EMAIL") or "").strip().lower()
    if not email:
        return False
    try:
        hdr = (scope.headers.get("cf-access-authenticated-user-email") or "").strip().lower()
    except Exception:
        hdr = ""
    return bool(hdr) and hdr == email


def invite_ok(scope) -> bool:
    """May this request enter an invite_required community? (owner OR valid token).
    Unlike the workspace gate there is no "empty → open" fallback: an
    invite_required community with no tokens configured admits only the owner."""
    if is_owner(scope):
        return True
    tok = request_token(scope)
    return bool(tok) and tok in community_tokens()


def touch(scope) -> None:
    """Record a token use (admin 'who's using' view). Best-effort."""
    tok = request_token(scope)
    if not tok:
        return
    try:
        from glimi.dashboard import invites
        invites.touch(tok)
    except Exception:
        pass


def remember_cookie(response, scope) -> None:
    """If a *valid* community token arrived via ``?invite=``, remember it so reloads
    stay unlocked without re-passing the query."""
    try:
        tok = (scope.query_params.get("invite") or "").strip()
    except Exception:
        return
    if tok and tok in community_tokens():
        response.set_cookie(INVITE_COOKIE, tok, max_age=2592000,
                            httponly=True, samesite="lax")
