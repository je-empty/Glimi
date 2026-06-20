"""apps/workspace/server.py — one Workspace server hosting N workspaces.

The Workspace analogue of the Community platform's "one process → N communities":
a single FastAPI server that owns a :class:`WorkspaceRegistry` and serves, for
each workspace, the SAME read-only Core dashboard (``glimi/dashboard``) under a
per-id prefix ``/w/{id}``.

Three things live here:

1. A **Demo** workspace, always present, read-only + visibly live — the seeded
   launch team from :mod:`demo`, with its ``activity_loop`` running on a daemon
   thread (so the dashboard keeps updating with zero setup, offline, $0).
2. A **home** page (``templates/home.html``) listing every workspace as a card and
   a "create workspace" form (name + goal).
3. **User-created** workspaces: ``POST /api/workspaces`` constructs a fresh
   ``Glimi(backend="echo")``, builds the real interaction topology via
   ``run.run_workspace`` (echo → fast, deterministic, a genuine interaction web),
   and registers it.

Kernel-only boundary, like the rest of Glimi Workspace: imports ``glimi``,
``fastapi``, and stdlib — never ``src`` / Discord.

The global-singleton constraint
-------------------------------
The kernel's runtime WRITE path is a process global (``glimi.runtime._store``,
set by ``Glimi.__init__``). The dashboard READ path is store-explicit
(``DashboardReader(store)``), so N stores are viewed independently and safely.
But any code that calls ``runtime.generate_*`` writes to whatever store was wired
last. So:

- Reads (every ``/w/{id}/api/*`` endpoint) build a per-request reader on that
  workspace's store — fully independent, any number in parallel.
- Builds (``run_workspace``, which DOES call ``runtime.generate_*``) are
  SERIALIZED under one lock: constructing each ``Glimi`` re-points the global to
  its own store, so only one build may run at a time. Echo makes a build instant.
- The Demo's ``activity_loop`` mutates ``g.store`` directly and never calls
  ``runtime.generate_*``, so it is safe to run alongside reads + serialized builds.

Run it (needs ``pip install "glimi[dashboard]"``)::

    PYTHONPATH=. python apps/workspace/run.py --server     # → http://127.0.0.1:8800
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

import glimi.dashboard as _dashboard
import glimi.runtime as _kr   # kernel runtime singleton (module-global store/cache)
import glimi.memory as _km    # kernel memory layer (shares the same DI globals)
from glimi import Glimi
from glimi.dashboard import DashboardReader

# Public reader-derived helpers (zero-dep) for the read-only endpoint shapes.
# Public API so the workspace consumes only the supported glimi.dashboard surface
# (no underscore-private internals) — important for the standalone-repo split.
from glimi.dashboard import (
    channel_detail as _channel_detail,
    owner_info as _owner_info,
    enrich_snapshot as _enrich_snapshot,
)

# Import the sibling app modules the same dual-path way run.py does, so this works
# whether loaded as ``apps.workspace.server`` or from a flat dir on sys.path.
try:  # script / flat-dir on sys.path
    import demo as _demo  # type: ignore
    from run import run_workspace  # type: ignore
    from team import TEAM  # type: ignore
except ImportError:  # imported as apps.workspace.server
    from . import demo as _demo
    from .run import run_workspace
    from .team import TEAM

# Shared invite-token store (the central admin on the landing manages it; this app
# only gates on tokens whose target is "workspace"). Lives in the kernel's shared
# web layer so all three apps use one store.
from glimi.dashboard import invites as _invites

# The Core dashboard ships the canonical rich UI — assets (css/js), the shared
# templates (dashboard/_core.html + _chat_shell.html), and the i18n dicts. This
# app consumes them straight from the installed ``glimi[dashboard]`` package; it
# keeps NO copy of its own (single source of truth → no drift across the split).
_DASH_DIR = Path(_dashboard.__file__).resolve().parent
_DASH_STATIC = _DASH_DIR / "static"
_DASH_TEMPLATES = _DASH_DIR / "templates"
_DASH_I18N = _DASH_DIR / "i18n"

# This app's own dir — the home (workspace picker) page + the presenter child
# template are workspace-local; the dashboard itself is the shared Core template.
_APP_DIR = Path(__file__).resolve().parent
_RESOURCES = _APP_DIR.parent.parent / "resources"  # repo-root /resources (logo, etc.)


def _asset_ver() -> str:
    """Cache-busting token = short hash of the newest canonical dashboard-asset
    mtime. Appended to asset URLs so a returning visitor never gets a stale copy,
    while still caching within a release. Recomputed at import (changes only when
    the shipped assets do)."""
    try:
        latest = max(
            (p.stat().st_mtime for p in _DASH_STATIC.rglob("*") if p.is_file()),
            default=0.0,
        )
    except Exception:
        latest = 0.0
    return hashlib.sha1(f"{latest}".encode("utf-8")).hexdigest()[:8]


_ASSET_VER = _asset_ver()

# Jinja env: the workspace's own templates (home.html) + the canonical Core
# templates (dashboard/_core.html, _chat_shell.html). The dashboard renders with a
# workspace context — user=None + caps hide the sim-only chrome, api_base=/w/{id}
# retargets the shared dashboard.js — but the markup is the single shared source.
from fastapi.templating import Jinja2Templates  # noqa: E402
_TEMPLATES = Jinja2Templates(directory=[str(_APP_DIR / "templates"), str(_DASH_TEMPLATES)])
_I18N_DIR = _DASH_I18N
# Tabs the workspace exposes; everything else (scenes/achievements/supervisors/
# sync/events/health/logs) is a Community sim feature → hidden via data-caps.
_WS_CAPS = {
    "scenes": False, "achievements": False, "supervisors": False,
    "sync": False, "events": False, "health": False, "logs": False,
}

# Backend for USER workspaces (build + chat). The chat brain (provider selection +
# the Claude CLI / Ollama / echo backends + budget cap) all live in Glimi Core
# (glimi.runtime / glimi.llm) — this app doesn't implement a backend, it just lets
# Core's config-driven selection run, exactly like Community ("no backend is
# forced"). Captured at import, BEFORE the demo / any build constructs a Glimi (each
# sets GLIMI_LLM_BACKEND on construction). Operator opts into a real backend via the
# env (e.g. GLIMI_LLM_BACKEND=ollama → free local, =claude_cli → metered); default
# is the offline echo placeholder. The Demo always stays echo ($0).
_USER_BACKEND = (os.environ.get("GLIMI_LLM_BACKEND") or "echo").strip() or "echo"

# Demo identities. Two entries are built from the SAME seeded launch team
# (``demo.build``):
#   • ``demo`` (/w/demo)       — public, always exposed, read-only (browse only).
#   • ``demo-live`` (/w/demo-live) — the Presenter twin: identical seeded state but
#     chat-ENABLED so the owner can demo live + keep using it. Unlisted on the
#     public home (``cards()`` skips it); reset to the seeded state via POST .../reset.
_DEMO_TITLE = "런칭 데모"
_PRESENTER_ID = "demo-live"
_PRESENTER_TITLE = "런칭 데모"

# ── invite gating (presenter chat + workspace creation) ─────────────────────
# When GLIMI_INVITE_TOKENS is set, the chat-ENABLED surfaces — the presenter
# (/w/demo-live) and creating a workspace — require either:
#   • the OWNER, recognized by Cloudflare Access' verified-email header (no token), or
#   • a guest with ?invite=<token> (a REUSABLE share link; remembered in a cookie).
# Unset → no gate (fully open: the OSS/local default). The public read-only demo
# (/w/demo) is NEVER gated. The owner email is GLIMI_OWNER_EMAIL (the address
# allowed through CF Access). Tokens come from two sources, unioned and re-read
# LIVE per request so the owner can ISSUE or REVOKE a token without a restart:
#   • GLIMI_INVITE_TOKENS      — comma-separated, fixed at startup (simple/CI), and
#   • GLIMI_INVITE_TOKENS_FILE — a file with one token per line (# comments ok);
#     issue = `echo <token> >> file`, revoke = delete its line. (per-person links)
_INVITE_TOKENS = {t.strip() for t in (os.environ.get("GLIMI_INVITE_TOKENS") or "").split(",") if t.strip()}
_INVITE_TOKENS_FILE = (os.environ.get("GLIMI_INVITE_TOKENS_FILE") or "").strip()
_OWNER_EMAIL = (os.environ.get("GLIMI_OWNER_EMAIL") or "").strip().lower()
_INVITE_COOKIE = "glimi_invite"


def _invite_tokens() -> set:
    """The currently-valid invite tokens: the env set ∪ the live token file
    (re-read each call → issue/revoke with no restart). Empty → gate disabled."""
    toks = set(_INVITE_TOKENS)
    if _INVITE_TOKENS_FILE:
        try:
            with open(_INVITE_TOKENS_FILE, encoding="utf-8") as f:
                for ln in f:
                    s = ln.strip()
                    if s and not s.startswith("#"):
                        toks.add(s.split()[0])  # first field — ignore an inline "# label"
        except OSError:
            pass
    toks |= _invites.token_set(target="workspace")  # admin-panel-managed (this app's target)
    return toks


def _touch_invite(scope) -> None:
    """Record usage of a managed token (for the admin panel's 'who's using' view).
    Owner (CF) requests carry no token → no-op. Best-effort."""
    tok = (scope.query_params.get("invite") or scope.cookies.get(_INVITE_COOKIE) or "").strip()
    if tok:
        _invites.touch(tok)


def _is_owner(scope) -> bool:
    """True if Cloudflare Access authenticated this request as the owner — CF sets
    ``Cf-Access-Authenticated-User-Email`` after its email login. Works for a
    Request or a WebSocket (both carry case-insensitive headers)."""
    if not _OWNER_EMAIL:
        return False
    email = (scope.headers.get("cf-access-authenticated-user-email") or "").strip().lower()
    return email == _OWNER_EMAIL


def _invite_ok(scope) -> bool:
    """Whether this request may use the chat-enabled / create surfaces. The owner
    (CF) always may; a valid invite token (``?invite=`` or remembered cookie) may.

    With NO tokens configured, fail OPEN only for a truly unconfigured (local/dev)
    deployment — i.e. no owner email set either. A deployment that set an owner email
    clearly intends gating, so it fails CLOSED (owner-only) rather than handing free
    chat / workspace creation to anyone (the presenter runs a real, paid/local model)."""
    if _is_owner(scope):
        return True
    toks = _invite_tokens()
    if not toks:
        return not _OWNER_EMAIL  # local/dev → open; public (owner email set) → closed
    tok = (scope.query_params.get("invite") or scope.cookies.get(_INVITE_COOKIE) or "").strip()
    return tok in toks


def _load_i18n(lang: str) -> dict:
    lang = (lang or "ko").lower()
    if lang not in ("ko", "en"):
        lang = "ko"
    try:
        with open(_I18N_DIR / f"dashboard.{lang}.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}

# Workspace chat avatars are role-based MONOGRAMS, not persona/anime faces. The
# workspace team is functional (Coordinator / Researcher / Builder / Critic), so
# a clean initial-on-tinted-disc reads better than a stock portrait — and keeps
# the avatar route dependency-free (no asset pool, always 200).
_ROLE_MONOGRAM = {
    "coordinator": "Co", "researcher": "Re", "builder": "Bu", "critic": "Cr",
}


def _monogram(agent_id: str) -> str:
    """A 1–2 char monogram for an agent id — role-aware and collision-free
    (Coordinator→Co, Critic→Cr, so the two C-roles never clash)."""
    s = (agent_id or "").strip()
    if not s:
        return "·"
    if s.lower() in _ROLE_MONOGRAM:
        return _ROLE_MONOGRAM[s.lower()]
    parts = [p for p in s.replace("_", " ").replace("-", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1]).upper()
    return (s[:1].upper() + s[1:2].lower()) if len(s) >= 2 else s[:1].upper()


# Role-specific hues so the team reads as branded, distinct discs (not random):
# Coordinator=amber, Researcher=blue, Builder=violet, Critic=rose. Others hash.
_ROLE_HUE = {"coordinator": 35, "researcher": 212, "builder": 265, "critic": 350}


def _avatar_svg(agent_id: str) -> str:
    """Inline SVG avatar: the agent's monogram on a soft vertical-gradient disc,
    tinted by ROLE (Coordinator/Researcher/Builder/Critic) for a branded, less-flat
    look. Always renders — no external asset, so the avatar route is always 200."""
    mono = _monogram(agent_id)
    aid = (agent_id or "").strip().lower()
    hue = _ROLE_HUE.get(aid, int(hashlib.sha1(aid.encode("utf-8")).hexdigest(), 16) % 360)
    fs = 38 if len(mono) >= 2 else 46
    gid = f"g{hue}"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" '
        'viewBox="0 0 96 96" role="img">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue},60%,90%)"/>'
        f'<stop offset="1" stop-color="hsl({hue},52%,78%)"/></linearGradient></defs>'
        f'<rect width="96" height="96" rx="48" fill="url(#{gid})"/>'
        f'<text x="48" y="51" font-family="-apple-system,Segoe UI,Roboto,sans-serif" '
        f'font-size="{fs}" font-weight="700" fill="hsl({hue},55%,30%)" '
        f'text-anchor="middle" dominant-baseline="central">{_esc(mono)}</text>'
        '</svg>'
    )


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── registry ──────────────────────────────────────────────────────────────────

@dataclass
class Workspace:
    """One hosted workspace: its Glimi (→ store) plus display metadata."""

    id: str
    glimi: Glimi
    title: str
    goal: str
    kind: str  # "demo" (public read-only) | "presenter" (chat-enabled twin) | "user"
    created_at: str = field(default_factory=_now_utc_iso)

    @property
    def store(self):
        return self.glimi.store

    def reader(self) -> DashboardReader:
        """A fresh store-explicit reader for this workspace (read path is safe)."""
        return DashboardReader(self.store)

    def card(self) -> dict:
        """The summary shape the home page's cards consume."""
        snap = self.reader().snapshot()
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "kind": self.kind,
            "agents": len(snap.get("agents", [])),
            "channels": len(snap.get("channels", [])),
            "created_at": self.created_at,
        }


class WorkspaceRegistry:
    """In-memory ``id -> Workspace`` map. A lock serializes LIVE builds (the
    create path calls ``runtime.generate_*``, which writes the process-global
    store — see the module docstring). Reads need no lock (store-explicit)."""

    def __init__(self) -> None:
        self._by_id: dict[str, Workspace] = {}
        self._lock = threading.Lock()  # serializes builds (global-singleton WRITE)
        self._seq = 0

    def get(self, ws_id: str) -> Optional[Workspace]:
        return self._by_id.get(ws_id)

    def cards(self) -> list[dict]:
        """Demo first, then user workspaces oldest → newest. The presenter twin is
        intentionally UNLISTED — it's the owner's private live-demo entry, reachable
        only by direct URL so the public home shows just the read-only demo."""
        demos = [w for w in self._by_id.values() if w.kind == "demo"]
        users = [w for w in self._by_id.values() if w.kind == "user"]
        users.sort(key=lambda w: w.created_at)
        return [w.card() for w in (*demos, *users)]

    def register(self, ws: Workspace) -> None:
        self._by_id[ws.id] = ws

    def _next_user_id(self) -> str:
        self._seq += 1
        return f"ws{self._seq}"

    def create(self, name: str, goal: str) -> Workspace:
        """Build a real-topology workspace under the build lock, on the configured
        backend (``_USER_BACKEND`` — echo by default; a real model when the operator
        sets ``GLIMI_LLM_BACKEND``).

        Serialized because ``run_workspace`` drives ``runtime.generate_*`` against
        the process-global store; constructing the ``Glimi`` re-points that global to
        this workspace's store, so only one build may be in flight at a time. On the
        echo backend each build is instant + deterministic; on a real backend the
        create runs the team on the goal (the workspace's first deliverable).
        """
        owner_name = (name or "Owner").strip() or "Owner"
        goal = (goal or "").strip() or "Plan the public launch of our open-source project"
        with self._lock:
            g = Glimi(backend=_USER_BACKEND, owner_name=owner_name)
            for aid, disp, atype, persona in TEAM:
                g.add_agent(aid, name=disp, persona=persona, agent_type=atype)
            # Real interaction topology (echo) → a genuine interaction web for goal.
            run_workspace(g, owner_name, goal)
            ws_id = self._next_user_id()
            ws = Workspace(id=ws_id, glimi=g, title=goal, goal=goal, kind="user")
            self.register(ws)
        return ws

    def run_in_ws(self, ws: "Workspace", fn):
        """Run ``fn`` with the kernel runtime/memory module-globals scoped to ``ws``
        — under the build lock, so it serializes with builds and other chats (the
        only callers that drive ``runtime.generate_*`` against the process-global
        store / ``_active_agents`` cache; the demo loop is store-only).

        The kernel ``runtime`` is a singleton whose store / profiles / owner /
        observer and ``_active_agents`` cache are shared across workspaces (agent
        ids collide — every workspace has a ``coordinator``). Each ``Glimi`` points
        those globals at its own instances on construction (last wins), so before a
        turn we re-point them to THIS workspace and clear the agent cache so it
        re-activates from this workspace's profiles/store (cross-tenant safety)."""
        g = ws.glimi
        with self._lock:
            for mod in (_kr, _km):
                mod.set_store(g.store)
                mod.set_profiles(g.profiles)
                mod.set_owner(g.owner)
                mod.set_observer(g.observer)
            _kr.runtime._active_agents.clear()  # force re-activation from this ws
            # Pin the backend to THIS workspace's for the turn (the kernel's
            # provider selection reads GLIMI_LLM_BACKEND; other constructions may
            # have moved it). Restored after — all under the lock, so no race.
            _prev = os.environ.get("GLIMI_LLM_BACKEND")
            if g._backend:
                os.environ["GLIMI_LLM_BACKEND"] = g._backend
            try:
                return fn()
            finally:
                if _prev is None:
                    os.environ.pop("GLIMI_LLM_BACKEND", None)
                else:
                    os.environ["GLIMI_LLM_BACKEND"] = _prev

    def rebuild(self, ws_id: str, builder, *, kinds=("presenter",)) -> Optional["Workspace"]:
        """Reset a workspace to a fresh seeded state: swap its ``Glimi`` for one from
        ``builder()``, under the build lock. Held because constructing a ``Glimi``
        re-points the process-global kernel runtime (same hazard as create / chat),
        so the rebuild must serialize with them. Restricted to ``kinds`` (presenter
        only) so the public demo and user workspaces can't be wiped."""
        with self._lock:
            ws = self._by_id.get(ws_id)
            if ws is None or ws.kind not in kinds:
                return None
            ws.glimi = builder()
            return ws


# ── per-workspace dashboard endpoint shapes (mirror glimi/dashboard/app.py) ───

def _snapshot_payload(reader: DashboardReader) -> dict:
    """``/api/snapshot`` in the rich dashboard shape. This is exactly the canonical
    :func:`glimi.dashboard.enrich_snapshot` — the kernel ships the enricher so the
    SAME shape (graph / KPIs / agent cards) renders for the kernel demo, a
    workspace, and any ``KernelStore`` population. Kept as a thin alias so the
    route reads naturally and a workspace-specific tweak would have one home."""
    return _enrich_snapshot(reader)


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _ws_postable(channel: str) -> bool:
    """Owner-postable channels: DMs + group rooms. ``internal-*`` (agent-only) and
    anything else are read-only (the owner watches, doesn't post)."""
    c = (channel or "").strip()
    if not c or c.startswith("internal-"):
        return False
    return c.startswith("dm-") or c.startswith("group-")


def _ws_agent_for(channel: str, frame_agent: str) -> str:
    """Which agent answers an owner turn: a ``dm-<agent>`` channel → that agent;
    a group room → the frame's explicit agent (v1 single responder), defaulting to
    the Coordinator."""
    c = (channel or "").strip()
    if c.startswith("dm-"):
        return c[3:] or "coordinator"
    return (frame_agent or "").strip() or "coordinator"


def _ws_speaker_name(ws: "Workspace", agent_id: str) -> str:
    try:
        return (ws.store.get_agent(agent_id) or {}).get("name") or agent_id
    except Exception:
        return agent_id


# ── chat read-APIs (per-workspace) — mirror src/platform/routers/chat.py shapes ─
#
# These are the EXACT JSON contracts the copied chat.js expects, rebuilt on the
# kernel store (store-explicit reads → safe for N workspaces in parallel) with NO
# `src` import. The store rows carry only id/channel/speaker/message/... — the
# display fields (display_name / is_user) the client needs are computed HERE (the
# Workspace layer), never pushed into the kernel store.

def _chat_owner(reader: DashboardReader) -> tuple[str, set[str]]:
    """(owner display name, set of owner ids) for is_user / display resolution."""
    name, ids = _owner_info(reader)
    return name, set(ids)


def _agent_name_map(reader: DashboardReader) -> dict[str, str]:
    """``agent_id → display name`` for every agent (resolves message speakers)."""
    return {a["id"]: (a.get("name") or a["id"]) for a in reader.agents()}


def _last_preview(store, channel: str, owner_ids: set[str],
                  names: dict[str, str], owner_name: str) -> Optional[dict]:
    """The channel's most recent message as a sidebar preview, or None.

    Shape matches chat.js's ``updateChannelPreviewFromHistory`` reader:
    ``{display_name, is_user, text, timestamp}``.
    """
    try:
        recent = store.get_recent_messages(channel, 1)
    except Exception:
        return None
    if not recent:
        return None
    r = recent[-1]
    speaker = r.get("speaker") or ""
    is_user = speaker in owner_ids
    disp = owner_name if is_user else (names.get(speaker) or speaker)
    return {
        "display_name": disp,
        "is_user": is_user,
        "text": (r.get("message") or "")[:120],
        "timestamp": r.get("timestamp") or "",
    }


def _list_chat_channels(ws: "Workspace") -> list[dict]:
    """The workspace's chat channels: a DM per agent (synthesized ``dm-<id>``,
    ordered mgr/coordinator-ish first via ``reader.agents()``) plus the registered
    ``group-*`` channels. Mirrors ``chat.py._list_postable_channels``.
    """
    reader = ws.reader()
    store = ws.store
    owner_name, owner_ids = _chat_owner(reader)
    names = _agent_name_map(reader)

    out: list[dict] = []
    # DM-per-agent. reader.agents() is already mgr → creator → dev → persona → id.
    for a in reader.agents():
        aid = a.get("id")
        if not aid:
            continue
        dm_channel = f"dm-{aid}"
        out.append({
            "channel": dm_channel,
            "kind": "dm",
            "agent_id": aid,
            "name": a.get("name") or aid,
            "type": a.get("type", ""),
            "avatar_url": f"/w/{ws.id}/api/avatar?id={aid}&v={_ASSET_VER}",
            "last": _last_preview(store, dm_channel, owner_ids, names, owner_name),
        })
    # Registered group channels (multi-agent). The overview lists every channel;
    # keep only ``group-*`` (mgr-/internal-/dm- are excluded by the prefix filter).
    try:
        overview = store.get_channel_overview()
    except Exception:
        overview = []
    for c in overview:
        name = c.get("channel") or ""
        if not name.startswith("group-"):
            continue
        out.append({
            "channel": name,
            "kind": "group",
            "agent_id": None,
            "name": name,
            "type": "group",
            "avatar_url": None,
            "last": _last_preview(store, name, owner_ids, names, owner_name),
        })
    return out


def _chat_history(ws: "Workspace", channel: str, limit: int) -> list[dict]:
    """Recent messages for ``channel`` (ASC by id), display-ready. Mirrors
    ``chat.py._channel_history``: resolves speaker → display name + is_user,
    passes the store's compact ``reactions`` summary through, and resolves a
    reply quote from the loaded window when the parent is present.
    """
    reader = ws.reader()
    store = ws.store
    owner_name, owner_ids = _chat_owner(reader)
    names = _agent_name_map(reader)

    try:
        rows = store.get_recent_messages(channel, limit)
    except Exception:
        rows = []
    # get_recent_messages already returns oldest→newest within the window; sort by
    # id to be explicit (ASC) so the client renders in order.
    rows = sorted(rows, key=lambda r: (r.get("id") or 0))
    by_id = {r.get("id"): r for r in rows if r.get("id") is not None}

    def _disp(speaker: str) -> tuple[str, bool]:
        is_user = speaker in owner_ids
        return (owner_name if is_user else (names.get(speaker) or speaker)), is_user

    out: list[dict] = []
    for r in rows:
        speaker = r.get("speaker") or ""
        disp, is_user = _disp(speaker)
        # Resolve the reply quote from the loaded window (else a bare pointer).
        reply_to = None
        parent_id = r.get("reply_to")
        if parent_id is not None:
            parent = by_id.get(parent_id)
            if parent is not None:
                p_speaker = parent.get("speaker") or ""
                p_disp, p_is_user = _disp(p_speaker)
                reply_to = {
                    "id": parent_id,
                    "author": p_disp,
                    "author_id": p_speaker,
                    "is_user": p_is_user,
                    "preview": (parent.get("message") or "")[:120],
                }
            else:
                reply_to = {"id": parent_id}
        out.append({
            "id": r.get("id"),
            "speaker_id": speaker,
            "display_name": disp,
            "is_user": is_user,
            "text": r.get("message") or "",
            "timestamp": r.get("timestamp") or "",
            # The store's _summarize_reactions already yields {emoji,count,actors}.
            "reactions": r.get("reactions") or [],
            "reply_to": reply_to,
            "thread_root": r.get("thread_root"),
            "images": [],  # not modeled in the kernel store — stable client shape
        })
    return out


def _render_core(request: "Request", ws: "Workspace", *, active_tab: str,
                 refresh_ms: int = 0):
    """Render the canonical Core dashboard (``dashboard/_core.html``) for a
    workspace: user=None + ``_WS_CAPS`` hide the sim-only chrome, api_base=/w/{id}
    retargets the shared dashboard.js, KO/EN picker built in. The markup is the
    single shared source — only this context differs from the kernel/community."""
    owner_name, _ = _chat_owner(ws.reader())
    # Default to Korean (primary audience); the built-in KO/EN picker (🌐) switches.
    lang = (request.query_params.get("lang") or "ko").lower()
    if lang not in ("ko", "en"):
        lang = "ko"
    ctx = {
        "request": request,
        "static_base": "/static",
        "api_base": f"/w/{ws.id}",
        "caps_json": json.dumps(_WS_CAPS),
        "community_chrome": False,
        "brand_logo": True,            # show the Glimi logo (served at /logo) in the brand
        "active_tab": active_tab,
        "user": None,
        "community_id": None,           # workspace uses api_base, not ?community=
        "community_name": ws.title,
        "language": lang,
        "read_only": (ws.kind == "demo")
                     or (ws.kind == "presenter" and not _invite_ok(request)),
        "asset_v": _ASSET_VER,
        "chat_channel": "dm-coordinator",
        "chat_agent": "coordinator",
        "chat_user": owner_name or "You",
        "refresh_ms": refresh_ms or "",
    }
    # The presenter twin renders a thin child of the canonical shell that adds the
    # owner-only "reset to initial state" control (extra_chrome/extra_scripts).
    template = ("dashboard/presenter.html" if ws.kind == "presenter"
                else "dashboard/_core.html")
    resp = _TEMPLATES.TemplateResponse(request, template, ctx)
    resp.headers["Cache-Control"] = "no-store"
    # Remember a valid presenter invite (reusable share link) in a cookie so the
    # chat socket + reloads stay unlocked without re-passing ?invite= each time.
    _tok = (request.query_params.get("invite") or "").strip()
    if ws.kind == "presenter" and _tok and _tok in _invite_tokens():
        resp.set_cookie(_INVITE_COOKIE, _tok, max_age=2592000, httponly=True, samesite="lax")
    if ws.kind == "presenter":
        _touch_invite(request)  # record usage for the admin panel's 'who's using' view
    return resp


# ── app ───────────────────────────────────────────────────────────────────────

def create_app(registry: Optional[WorkspaceRegistry] = None,
               *, with_demo: bool = True,
               demo_interval: float = 6.0) -> FastAPI:
    """Build the multi-workspace FastAPI app.

    Registers the Demo workspace (unless ``with_demo`` is False — tests use that
    to exercise an empty registry) and starts its live activity loop on a daemon
    thread. The server owns serving; the demo loop only mutates its own store.
    """
    reg = registry or WorkspaceRegistry()
    app = FastAPI(title="Glimi Workspace — Server", docs_url=None, redoc_url=None)
    app.state.registry = reg

    # All dashboard assets (css / js) are the canonical Core ones, served from the
    # installed glimi[dashboard] package — single source, no workspace-local copy.
    app.mount("/static", StaticFiles(directory=str(_DASH_STATIC)), name="static")

    if with_demo:
        _install_demo(reg, interval=demo_interval)
        _install_presenter(reg)

    def _require(ws_id: str) -> Workspace:
        ws = reg.get(ws_id)
        if ws is None:
            raise HTTPException(status_code=404, detail=f"unknown workspace: {ws_id}")
        return ws

    # ── home ──────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, lang: str = "ko"):
        """Workspace picker + create form. Korean-primary (the audience); ``?lang=en``
        switches. Rendered (not served static) so the landing copy localizes."""
        lang = (lang or "ko").lower()
        if lang not in ("ko", "en"):
            lang = "ko"
        resp = _TEMPLATES.TemplateResponse(
            request, "home.html",
            {"request": request, "lang": lang,
             # Only owners / valid-token holders see the create form; anon visitors
             # get an invite-code entry instead (the public subdomain has no CF/login).
             "can_create": _invite_ok(request),
             "bad_invite": bool((request.query_params.get("invite") or "").strip())
                           and not _invite_ok(request)})
        resp.headers["Cache-Control"] = "no-store"
        # "start fresh" invite link: /?invite=TOKEN remembers the token (cookie) so
        # the create form is unlocked (gate otherwise 403s guests).
        _tok = (request.query_params.get("invite") or "").strip()
        if _tok and _tok in _invite_tokens():
            resp.set_cookie(_INVITE_COOKIE, _tok, max_age=2592000, httponly=True, samesite="lax")
        return resp

    @app.get("/logo")
    def logo() -> Response:
        """Glimi brand logo (SVG → PNG fallback) so the workspace top-left shows it
        like Community does, instead of a bare title."""
        for name, mt in (("Glimi-logo.svg", "image/svg+xml"), ("Glimi-logo.png", "image/png")):
            p = _RESOURCES / name
            if p.exists():
                return Response(content=p.read_bytes(), media_type=mt,
                                headers={"Cache-Control": "public, max-age=3600"})
        return Response(status_code=404)

    @app.get("/api/workspaces")
    def list_workspaces() -> JSONResponse:
        return JSONResponse(reg.cards())

    @app.post("/api/workspaces", response_model=None)
    async def create_workspace(request: Request):
        """Create a workspace from a form (browser) or JSON (API).

        Serialized by the registry's build lock (global-singleton WRITE path).
        Form submits get a 303 redirect to the new dashboard; JSON callers get
        ``{id, title, goal, kind, ...}``. Gated by invite when GLIMI_INVITE_TOKENS
        is set (owner via CF, or a valid token) so guests can't spam workspaces.
        """
        if not _invite_ok(request):
            raise HTTPException(status_code=403, detail="invite required to create a workspace")
        name = goal = ""
        is_form = False
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                body = await request.json()
            except Exception:
                body = {}
            name = str(body.get("name", "") or "")
            goal = str(body.get("goal", "") or "")
        else:
            is_form = True
            form = await request.form()
            name = str(form.get("name", "") or "")
            goal = str(form.get("goal", "") or "")
        ws = reg.create(name, goal)
        if is_form:
            return RedirectResponse(url=f"/w/{ws.id}", status_code=303)
        return JSONResponse(ws.card())

    # ── per-workspace dashboard ─────────────────────────────────────────────
    # Primary view = the Community-style chat (chat shell + sidebar/feed). The
    # connection graph (the previous /w/{id} Core dashboard) moves to /w/{id}/graph
    # and is reachable from the chat page's Overview nav.
    # no-store: the HTML must always re-fetch so its versioned asset refs
    # (chat.js?v=…, __GLIMI_ASSET_VER__) are current — otherwise a returning
    # visitor's cached page keeps pointing at stale assets/avatars.
    _NO_STORE = {"Cache-Control": "no-store"}

    @app.get("/w/{ws_id}", response_class=HTMLResponse)
    def dashboard(ws_id: str, request: Request) -> HTMLResponse:
        """The full Community-grade dashboard (chat + overview/graph + agents +
        channels + …), rendered from the shared templates with a workspace
        context: user=None + data-caps hide the sim-only chrome, API_BASE=/w/{id}
        retargets the shared dashboard.js, and the KO/EN picker comes built-in."""
        ws = _require(ws_id)
        return _render_core(request, ws, active_tab="chat")

    @app.get("/w/{ws_id}/api/i18n")
    def w_i18n(ws_id: str, lang: str = "ko") -> JSONResponse:
        """Dashboard chrome translations for the KO/EN picker (shared dicts)."""
        _require(ws_id)
        return JSONResponse(_load_i18n(lang))

    @app.get("/w/{ws_id}/graph", response_class=HTMLResponse)
    def dashboard_graph(ws_id: str, request: Request) -> HTMLResponse:
        """The connection-graph / overview view — the same shared dashboard opened
        on its Overview tab, with periodic refresh. Reachable from the chat page's
        Overview nav and direct links."""
        ws = _require(ws_id)
        return _render_core(request, ws, active_tab="overview", refresh_ms=6000)

    # ── per-workspace chat read-APIs (mirror the Community chat contract) ────
    @app.get("/w/{ws_id}/chat/channels")
    def w_chat_channels(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse({"channels": _list_chat_channels(ws)})

    @app.get("/w/{ws_id}/chat/history")
    def w_chat_history(ws_id: str, channel: str = "", limit: int = 50) -> JSONResponse:
        ws = _require(ws_id)
        channel = (channel or "").strip()
        if not channel:
            return JSONResponse({"error": "missing channel"}, status_code=400)
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50
        return JSONResponse({
            "channel": channel,
            "messages": _chat_history(ws, channel, limit),
        })

    @app.websocket("/w/{ws_id}/chat/ws")
    async def w_chat_ws(websocket: WebSocket, ws_id: str) -> None:
        """Live chat socket.

        Demo workspace = read-only (browse only). A user workspace accepts the
        owner's turns: the message is dispatched to the channel's agent through the
        kernel runtime **scoped to this workspace** (``reg.run_in_ws``), which logs
        the owner turn + the reply, and the reply line(s) stream back here. The
        kernel call is blocking, so it runs in an executor thread (the event loop
        stays responsive). ``ping`` → ``pong`` keeps the status 'Connected'.
        """
        ws = reg.get(ws_id)
        if ws is None:
            await websocket.close(code=1008)
            return
        read_only = (ws.kind == "demo") or (ws.kind == "presenter" and not _invite_ok(websocket))
        await websocket.accept()
        loop = asyncio.get_event_loop()
        try:
            while True:
                frame = await websocket.receive_json() or {}
                ftype = (frame.get("type") or "text").strip()
                channel = (frame.get("channel") or "").strip()

                if ftype == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                if ftype != "text":
                    continue  # WS-1 scope = the owner→agent turn; reactions/threads later
                if not channel:
                    await websocket.send_json({"type": "error", "error": "missing channel"})
                    continue
                if read_only:
                    await websocket.send_json({
                        "type": "error", "channel": channel, "error": "demo_readonly",
                        "message": "Demo — read-only. Create your own workspace to chat with the team.",
                    })
                    continue
                if not _ws_postable(channel):
                    await websocket.send_json({
                        "type": "error", "channel": channel,
                        "error": "channel is not user-postable",
                    })
                    continue
                text = (frame.get("text") or "").strip()
                if not text:
                    await websocket.send_json({"type": "error", "error": "empty text"})
                    continue

                agent_id = _ws_agent_for(channel, frame.get("agent") or "")
                speaker = _ws_speaker_name(ws, agent_id)

                def _turn():
                    # store-explicit (safe); generate_response logs owner + reply.
                    ws.store.set_channel_participants(channel, [ws.glimi.owner.id(), agent_id])
                    return _kr.runtime.generate_response(agent_id, channel, text)

                await websocket.send_json({"type": "typing", "channel": channel,
                                           "agent_id": agent_id, "speaker": speaker, "on": True})
                try:
                    lines = await loop.run_in_executor(None, reg.run_in_ws, ws, _turn)
                except Exception as e:  # noqa: BLE001 — never hang the socket
                    await websocket.send_json({"type": "typing", "channel": channel,
                                               "agent_id": agent_id, "speaker": speaker, "on": False})
                    await websocket.send_json({"type": "error", "channel": channel,
                                               "error": "turn failed", "message": str(e)})
                    continue
                await websocket.send_json({"type": "typing", "channel": channel,
                                           "agent_id": agent_id, "speaker": speaker, "on": False})
                for line in (lines or []):
                    if (line or "").strip():
                        await websocket.send_json({
                            "type": "text", "channel": channel,
                            "agent_id": agent_id, "speaker": speaker, "text": line,
                        })
        except WebSocketDisconnect:
            pass
        except Exception:
            # Malformed frame / client gone — close quietly, never crash.
            pass

    # ── per-workspace chat avatars (workspace layer; no kernel image field) ──
    @app.get("/w/{ws_id}/api/avatar")
    def w_avatar(ws_id: str, id: str = "") -> Response:
        """Role-based monogram avatar (inline SVG). The workspace team is
        functional (Coordinator/Researcher/Builder/Critic) — no persona/anime
        portraits here. Always 200."""
        _require(ws_id)
        return Response(content=_avatar_svg(id), media_type="image/svg+xml",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/w/{ws_id}/api/snapshot")
    def w_snapshot(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse(_snapshot_payload(ws.reader()))

    @app.get("/w/{ws_id}/api/agent_detail")
    @app.get("/w/{ws_id}/api/agent")  # rich dashboard.js openAgent() uses /api/agent
    def w_agent_detail(ws_id: str, id: str) -> JSONResponse:
        ws = _require(ws_id)
        if not id:
            raise HTTPException(status_code=422, detail="id required")
        return JSONResponse(ws.reader().agent_detail(id))

    @app.get("/w/{ws_id}/api/channel")
    def w_channel(ws_id: str, name: str) -> JSONResponse:
        ws = _require(ws_id)
        if not name:
            raise HTTPException(status_code=422, detail="name required")
        return JSONResponse(_channel_detail(ws.reader(), name))

    @app.get("/w/{ws_id}/api/tool_timeline")
    def w_tool_timeline(ws_id: str, limit: int = 50) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse(ws.reader().tool_timeline(limit=limit))

    @app.get("/w/{ws_id}/api/usage")
    def w_usage(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse(ws.reader().usage())

    # ── presenter: reset to the initial seeded state ────────────────────────
    @app.post("/w/{ws_id}/reset")
    def w_reset(ws_id: str) -> JSONResponse:
        """Rebuild the Presenter demo back to the seeded mockup state (clears every
        message the owner sent during a walkthrough). Presenter-only — the public
        demo and user workspaces can't be reset (the registry guards on kind)."""
        ws = _require(ws_id)
        if ws.kind != "presenter":
            raise HTTPException(status_code=403,
                                detail="reset is only available for the presenter demo")
        out = reg.rebuild(ws_id, lambda: _demo.build(backend=_USER_BACKEND))
        if out is None:
            raise HTTPException(status_code=404, detail="presenter demo not found")
        return JSONResponse({"status": "reset", "id": ws_id})

    # (The token-admin panel lives on the landing app — glimi.iruyo.com/admin —
    #  so one central panel manages both community + workspace invites.)
    return app


def _install_demo(reg: WorkspaceRegistry, *, interval: float = 6.0) -> Workspace:
    """Register the Demo workspace and start its live activity loop (daemon).

    Mirrors ``demo.run_demo`` WITHOUT the blocking serve — the server owns
    serving. The loop only mutates the demo's own store (no ``runtime.generate_*``),
    so it runs safely alongside reads + serialized creates.
    """
    g = _demo.build()
    ws = Workspace(id="demo", glimi=g, title=_DEMO_TITLE,
                   goal=_demo.GOAL, kind="demo")
    reg.register(ws)
    stop = threading.Event()
    thread = threading.Thread(
        target=_demo.activity_loop, args=(g, stop, interval), daemon=True,
        name="glimi-workspace-server-demo",
    )
    thread.start()
    # Daemon thread → dies with the process; server lifetime == demo lifetime, so
    # we don't expose a stop handle.
    return ws


def _install_presenter(reg: WorkspaceRegistry) -> Workspace:
    """Register the Presenter demo (``/w/demo-live``) — the chat-enabled twin of the
    public read-only demo, built from the SAME seeded launch team so the owner can
    open it for a live walkthrough and continue from the exact mockup state.

    Differences from the public demo: ``kind="presenter"`` (so chat is NOT
    read-only), built on ``_USER_BACKEND`` (real replies when the operator sets
    ``GLIMI_LLM_BACKEND``; echo/$0 otherwise), and NO activity loop — the state is
    owner-driven + stays stable for a demo, with ``POST .../reset`` rebuilding it
    back to the seeded mockup. Unlisted on the public home (see ``cards()``)."""
    g = _demo.build(backend=_USER_BACKEND)
    ws = Workspace(id=_PRESENTER_ID, glimi=g, title=_PRESENTER_TITLE,
                   goal=_demo.GOAL, kind="presenter")
    reg.register(ws)
    return ws


def serve(host: str = "127.0.0.1", port: int = 8800, **uvicorn_kwargs) -> int:
    """Run the multi-workspace server (blocking). Needs ``glimi[dashboard]``."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - import-guard message
        print(f"Dashboard deps not installed: {exc}")
        print('Install with:  pip install "glimi[dashboard]"')
        return 1

    app = create_app()
    url = f"http://{host}:{port}"
    print("=" * 64)
    print("  Glimi Workspace — SERVER (N workspaces)")
    print("=" * 64)
    print(f"  home : {url}              ← workspace list + create")
    print(f"  demo : {url}/w/demo       ← seeded live demo (read-only, public, $0)")
    print(f"  live : {url}/w/demo-live  ← presenter twin (chat ON, owner-only, resettable)")
    print("=" * 64 + "\n")
    uvicorn.run(app, host=host, port=port, **uvicorn_kwargs)
    return 0
