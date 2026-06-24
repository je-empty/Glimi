"""workspace/server.py — one Workspace server hosting N workspaces.

The Workspace analogue of the Community platform's "one process → N communities":
a single FastAPI server that owns a :class:`WorkspaceRegistry` and serves, for
each workspace, the SAME read-only Core dashboard (``glimi/dashboard``) under a
per-id prefix ``/w/{id}``.

Three things live here:

1. A **Demo** workspace, always present, read-only + visibly live — the seeded
   launch team from :mod:`demo`, with its ``activity_loop`` running on a daemon
   thread (so the dashboard keeps updating with zero setup, offline, $0).
2. A **home** page (the shared ``_demo_list.html`` from glimi/dashboard, identical
   to the Community demo list) listing every workspace as a card + a "create
   workspace" form (name + goal) unless ``GLIMI_DEMO_ONLY``.
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

    PYTHONPATH=. python workspace/run.py --server     # → http://127.0.0.1:8800
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
# whether loaded as ``workspace.server`` or from a flat dir on sys.path.
try:  # script / flat-dir on sys.path
    import demo as _demo  # type: ignore
    import demo_en as _demo_en  # type: ignore
    from run import add_team_member, run_workspace, seed_team  # type: ignore
    from team import RESERVED_IDS  # type: ignore
    from driver import drive_workspace  # type: ignore
    from owner_agent import OWNER_REVIEW_CHANNEL as _OWNER_REVIEW_CHANNEL  # type: ignore
except ImportError:  # imported as workspace.server
    from . import demo as _demo
    from . import demo_en as _demo_en
    from .run import add_team_member, run_workspace, seed_team
    from .team import RESERVED_IDS
    from .driver import drive_workspace
    from .owner_agent import OWNER_REVIEW_CHANNEL as _OWNER_REVIEW_CHANNEL

# Friendly display name + tooltip for the owner's read-only reasoning channel in
# the chat sidebar (KO default; chat.js's i18n can override via the chat.owner_review
# key). Renamed "오너의 검토" → "자동 진행 메모": when auto-run drives the workspace
# on the owner's behalf, the manager's review notes land here.
_OWNER_REVIEW_NAME = "자동 진행 메모"
_OWNER_REVIEW_TOOLTIP = "자동 진행(오너 대리) 시 매니저 검토 메모"

# The Core dashboard ships the canonical rich UI — assets (css/js), the shared
# templates (dashboard/_core.html + _chat_shell.html), and the i18n dicts. This
# app consumes them straight from the installed ``glimi[dashboard]`` package; it
# keeps NO copy of its own (single source of truth → no drift across the split).
_DASH_DIR = Path(_dashboard.__file__).resolve().parent
_DASH_STATIC = _DASH_DIR / "static"
_DASH_TEMPLATES = _DASH_DIR / "templates"
_DASH_I18N = _DASH_DIR / "i18n"

# This app's own dir — the home (workspace picker) page is workspace-local;
# the dashboard itself is the shared Core template.
_APP_DIR = Path(__file__).resolve().parent
_RESOURCES = _APP_DIR.parent / "assets" / "brand"  # repo-root /resources (logo, etc.)


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

# Jinja env: the canonical Core templates from glimi/dashboard (the shared
# _demo_list.html home + dashboard/_core.html + _chat_shell.html). The dashboard renders with a
# workspace context — user=None + caps hide the sim-only chrome, api_base=/w/{id}
# retargets the shared dashboard.js — but the markup is the single shared source.
from fastapi.templating import Jinja2Templates  # noqa: E402
_TEMPLATES = Jinja2Templates(directory=[str(_APP_DIR / "templates"), str(_DASH_TEMPLATES)])
# 공개 데모 배포에서만 설정 — 상단 랜딩(glimi.iruyo.com)으로 돌아가는 링크 노출.
# 미설정(로컬/OSS)이면 빈 문자열 → 템플릿이 링크를 렌더하지 않는다.
_TEMPLATES.env.globals["landing_url"] = os.environ.get("GLIMI_LANDING_URL", "")
_I18N_DIR = _DASH_I18N
# Tabs the workspace exposes; everything else (scenes/achievements/supervisors/
# sync/events/health/logs) is a Community sim feature → hidden via data-caps.
_WS_CAPS = {
    "scenes": False, "achievements": False, "supervisors": False,
    "sync": False, "events": False, "health": False, "logs": False,
}
# 데모 워크스페이스에서만 supervisor 뷰를 켠다(합성 관찰 데이터로 시연). 사용자가 만든
# 워크스페이스는 실제 supervisor 런타임이 아직 없어 OFF 유지 — 추후 실구현 시 일괄 전환.
_WS_CAPS_DEMO = {**_WS_CAPS, "supervisors": True}

# Backend for USER workspaces (build + chat). The chat brain (provider selection +
# the Claude CLI / Ollama / echo backends + budget cap) all live in Glimi Core
# (glimi.runtime / glimi.llm) — this app doesn't implement a backend, it just lets
# Core's config-driven selection run, exactly like Community ("no backend is
# forced"). Captured at import, BEFORE the demo / any build constructs a Glimi (each
# sets GLIMI_LLM_BACKEND on construction). Operator opts into a real backend via the
# env (e.g. GLIMI_LLM_BACKEND=ollama → free local, =claude_cli → metered); default
# is the offline echo placeholder. The Demo always stays echo ($0).
_USER_BACKEND = (os.environ.get("GLIMI_LLM_BACKEND") or "echo").strip() or "echo"

# Demo-only deployment switch (off by default — OSS users get the full create flow).
# When GLIMI_DEMO_ONLY is set, the hosted instance shows ONLY the seeded demo: the
# create form is hidden, the create endpoint 403s, and persisted user workspaces are
# not restored. Used by the owner's public showcase so visitors can't spin up workspaces.
_DEMO_ONLY = (os.environ.get("GLIMI_DEMO_ONLY") or "").strip().lower() not in ("", "0", "false", "no")

# Demo identities. Two entries are built from the SAME seeded launch team
# (``demo.build``):
#   • ``demo`` (/w/demo)       — public, always exposed, read-only (browse only).
_DEMO_TITLE = "출시 기획 데모"


def _load_i18n(lang: str) -> dict:
    lang = (lang or "ko").lower()
    if lang not in ("ko", "en"):
        lang = "ko"
    try:
        with open(_I18N_DIR / f"dashboard.{lang}.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


# 서버사이드 i18n — 대시보드 chrome(탭·KPI·섹션)을 언어에 맞게 렌더. 사용: {{ t('tab_overview', language) }}
_I18N_T_CACHE: dict = {}


def _t_global(key: str, lang: str = "ko") -> str:
    lang = lang if lang in ("ko", "en") else "ko"
    if lang not in _I18N_T_CACHE:
        d = _load_i18n(lang)
        _I18N_T_CACHE[lang] = d if "error" not in d else {}
    return _I18N_T_CACHE[lang].get(key) or _I18N_T_CACHE.get("ko", {}).get(key) or key


_TEMPLATES.env.globals["t"] = _t_global

# Workspace chat avatars are role EMOJIS on a role-hued disc, not persona/anime
# faces and not 2-letter monograms. The workspace team is functional (manager /
# researcher / builder / critic), so a clear role icon reads instantly — and keeps
# the avatar route dependency-free (no asset pool, always 200).
#   🧭 manager/coordinator · 🔬 researcher · 🛠 builder · 🔍 critic · ✍️ writer
# A manager-proposed DYNAMIC role maps via its role keyword (designer→🎨, …); any
# unknown id/keyword falls back to 🧩 (generic teammate), so the route is always 200.
_ROLE_EMOJI = {
    "coordinator": "🧭", "manager": "🧭", "lead": "🧭", "strategist": "🧭",
    "researcher": "🔬", "research": "🔬", "analyst": "📊", "data": "📊",
    "builder": "🛠", "engineer": "🛠", "developer": "🛠", "maker": "🛠",
    "critic": "🔍", "reviewer": "🔍", "qa": "🔍", "tester": "🔍",
    "writer": "✍️", "editor": "✍️", "copywriter": "✍️",
    "designer": "🎨", "design": "🎨",
    "marketer": "📣", "marketing": "📣", "growth": "📣",
    "planner": "🗂", "pm": "🗂", "product": "🗂",
    "advisor": "🧠", "expert": "🧠", "specialist": "🧩",
}
_GENERIC_EMOJI = "🧩"


def _role_emoji(agent_id: str, role_keyword: str = "") -> str:
    """The role emoji for an agent — keyed by id first, then a role keyword (for a
    dynamic role whose id isn't in the static map), with a 🧩 fallback so any id
    always renders an icon (never a bare letter)."""
    aid = (agent_id or "").strip().lower()
    if aid in _ROLE_EMOJI:
        return _ROLE_EMOJI[aid]
    kw = (role_keyword or "").strip().lower()
    if kw in _ROLE_EMOJI:
        return _ROLE_EMOJI[kw]
    return _GENERIC_EMOJI


# Role-specific hues so the team reads as branded, distinct discs (not random):
# Coordinator=amber, Researcher=blue, Builder=violet, Critic=rose. Others hash.
_ROLE_HUE = {"coordinator": 35, "researcher": 212, "builder": 265, "critic": 350}


def _avatar_svg(agent_id: str, role_keyword: str = "") -> str:
    """Inline SVG avatar: the agent's ROLE EMOJI (🧭/🔬/🛠/🔍/✍️, 🧩 fallback) on a
    soft vertical-gradient disc, tinted by ROLE (manager/researcher/builder/critic)
    for a branded, less-flat look. A dynamic role's emoji comes from ``role_keyword``
    when its id isn't a known role. Always renders — no external asset, so the avatar
    route is always 200."""
    emoji = _role_emoji(agent_id, role_keyword)
    aid = (agent_id or "").strip().lower()
    hue = _ROLE_HUE.get(aid, int(hashlib.sha1(aid.encode("utf-8")).hexdigest(), 16) % 360)
    gid = f"g{hue}"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" '
        'viewBox="0 0 96 96" role="img">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue},60%,90%)"/>'
        f'<stop offset="1" stop-color="hsl({hue},52%,78%)"/></linearGradient></defs>'
        f'<rect width="96" height="96" rx="48" fill="url(#{gid})"/>'
        '<text x="48" y="52" font-family="-apple-system,Segoe UI,Roboto,'
        '\'Apple Color Emoji\',\'Segoe UI Emoji\',sans-serif" '
        'font-size="50" text-anchor="middle" dominant-baseline="central">'
        f'{_esc(emoji)}</text>'
        '</svg>'
    )


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── user-workspace persistence (metadata; re-created deterministically at boot) ──

def _ws_store_path() -> str:
    """JSON file persisting user-created workspaces. Empty env → no persistence
    (in-memory only, as before). Read live so deploys/tests can point it anywhere."""
    return (os.environ.get("GLIMI_WORKSPACES_STORE") or "").strip()


def _load_ws_meta() -> list:
    p = _ws_store_path()
    if not p:
        return []
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_ws_meta(items: list) -> None:
    p = _ws_store_path()
    if not p:
        return
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass


def _persist_ws_meta(ws_id: str, owner_name: str, goal: str, created_at: str, *,
                     auto_run: bool = False, context: str = "",
                     backlog: Optional[list] = None, max_rounds: int = 5) -> None:
    """Persist a user workspace's metadata, replacing any prior entry by id. The
    autonomous-loop brief (``auto_run`` / ``context`` / ``backlog`` / ``max_rounds``)
    rides along so the toggle's state + brief survive a restart (the loop itself is
    NOT auto-resumed — see ``_restore_user_workspaces``)."""
    items = [it for it in _load_ws_meta() if it.get("id") != ws_id]  # replace by id
    items.append({
        "id": ws_id, "owner_name": owner_name, "goal": goal, "created_at": created_at,
        "auto_run": bool(auto_run), "context": context or "",
        "backlog": list(backlog or []), "max_rounds": int(max_rounds),
    })
    _save_ws_meta(items)


def _restore_user_workspaces(reg: "WorkspaceRegistry") -> None:
    """Rebuild persisted user workspaces at startup. The default echo backend is
    deterministic, so re-running ``create`` reproduces each workspace exactly (same
    id + timestamp). On a REAL backend, re-running would cost calls and drift, so
    persisted entries are skipped (a store snapshot would be the follow-up).

    The autonomous-loop brief (``auto_run`` / ``context`` / ``backlog`` /
    ``max_rounds``) is restored onto each Workspace, BUT the driver is deliberately
    NOT auto-resumed: restore leaves ``_driver_task=None`` (running=False). A run
    that the process lost mid-flight must not silently re-spend budget on boot — the
    owner re-arms via the /auto/start toggle. (``auto_run=True`` here is just the
    last-saved toggle state for the UI, not a live run.)"""
    meta = _load_ws_meta()
    if not meta:
        return
    if _USER_BACKEND != "echo":
        print(f"[workspace] {len(meta)} persisted workspace(s) skipped (backend={_USER_BACKEND!r}; "
              "deterministic re-create needs echo — store-snapshot persistence is a follow-up)")
        return
    n = 0
    for it in sorted(meta, key=lambda x: x.get("created_at", "")):
        try:
            reg.create(it.get("owner_name", "Owner"), it.get("goal", ""),
                       ws_id=it.get("id"), created_at=it.get("created_at"), persist=False,
                       auto_run=bool(it.get("auto_run", False)),
                       context=it.get("context", "") or "",
                       backlog=list(it.get("backlog", []) or []),
                       max_rounds=int(it.get("max_rounds", 5) or 5))
            n += 1
        except Exception as e:  # noqa: BLE001 — one bad entry must not break startup
            print(f"[workspace] restore skipped {it.get('id')}: {e}")
    print(f"[workspace] restored {n} user workspace(s) from {_ws_store_path()}")


# ── registry ──────────────────────────────────────────────────────────────────

@dataclass
class Workspace:
    """One hosted workspace: its Glimi (→ store) plus display metadata.

    The autonomous owner-driver loop (``workspace/driver.py``) adds a few fields:

    - ``auto_run`` / ``context`` / ``backlog`` / ``max_rounds`` are the persisted
      brief for the loop (round-tripped through ``_persist_ws_meta`` /
      ``_restore_user_workspaces``). ``auto_run`` is opt-in (default False) so a
      real-backend workspace never spends a cent unless the owner flips it on.
    - ``rounds_run`` / ``driver_reason`` are live run state, surfaced by
      ``GET /auto/status`` (not persisted — they reset per process).
    - ``_driver_task`` / ``_driver_cancel`` / ``_subscribers`` are non-serializable
      runtime handles (the asyncio task, its cancel Event, and the set of connected
      chat WebSockets for live fan-out); kept off persistence (compare=False).
    """

    id: str
    glimi: Glimi
    title: str
    goal: str
    kind: str  # "demo" (public read-only) | "user" (created workspace)
    created_at: str = field(default_factory=_now_utc_iso)

    # ── build lifecycle (the initial team-forming + first round) ──
    # "building" while the background create-build runs the first round; "ready"
    # once it finishes (or "error" if it failed). The demo is born ready. The
    # dashboard is reachable at /w/{id} the instant the record exists (status is
    # surfaced in the snapshot so the UI can show a "team forming…" banner that
    # clears on its own).
    status: str = "ready"

    # ── autonomous owner-driver brief (persisted) ──
    auto_run: bool = False
    context: str = ""
    backlog: list = field(default_factory=list)
    max_rounds: int = 5

    # ── live run state (not persisted; reset per process) ──
    rounds_run: int = 0
    driver_reason: str = ""  # last terminal reason: done|max_rounds|cancelled|budget

    # ── non-serializable runtime handles ──
    _driver_task: object = field(default=None, repr=False, compare=False)    # asyncio.Task|None
    _driver_cancel: object = field(default=None, repr=False, compare=False)  # threading.Event|None
    _build_task: object = field(default=None, repr=False, compare=False)     # _DriverHandle|None (initial build)
    _subscribers: set = field(default_factory=set, repr=False, compare=False)  # chat WS fan-out

    @property
    def store(self):
        return self.glimi.store

    @property
    def building(self) -> bool:
        """True while the initial create-build (team-forming + first round) is in
        flight on its background thread."""
        t = self._build_task
        return bool(t is not None and not getattr(t, "done", lambda: True)())

    @property
    def driver_running(self) -> bool:
        """True while the owner-driver background task is in flight."""
        t = self._driver_task
        return bool(t is not None and not getattr(t, "done", lambda: True)())

    def reader(self) -> DashboardReader:
        """A fresh store-explicit reader for this workspace (read path is safe)."""
        return DashboardReader(self.store)

    def card(self) -> dict:
        """The summary shape the home page's cards consume."""
        snap = self.reader().snapshot()
        agents = snap.get("agents", [])
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "kind": self.kind,
            # Live build status so the home card + dashboard can show "팀 꾸리는 중…"
            # the moment a workspace is created (before its first round finishes).
            "status": ("building" if self.building else self.status),
            "agents": len(agents),
            "channels": len(snap.get("channels", [])),
            "avatars": [
                {"name": a.get("name") or a.get("id"),
                 "avatar_url": f"/w/{self.id}/api/avatar?id={a.get('id')}&v={_ASSET_VER}"}
                for a in agents[:6]
            ],
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
        """Demo first, then user workspaces oldest → newest."""
        demos = [w for w in self._by_id.values() if w.kind == "demo"]
        users = [w for w in self._by_id.values() if w.kind == "user"]
        users.sort(key=lambda w: w.created_at)
        return [w.card() for w in (*demos, *users)]

    def register(self, ws: Workspace) -> None:
        self._by_id[ws.id] = ws

    def _next_user_id(self) -> str:
        self._seq += 1
        return f"ws{self._seq}"

    def create_record(self, name: str, goal: str, *, ws_id: Optional[str] = None,
                      created_at: Optional[str] = None, persist: bool = True,
                      auto_run: bool = False, context: str = "",
                      backlog: Optional[list] = None, max_rounds: int = 5) -> Workspace:
        """Create + register a workspace RECORD immediately, WITHOUT running the
        first round — the fast, non-blocking half of create.

        Constructing the ``Glimi`` is cheap (in-memory store, no LLM), so this
        returns in milliseconds and the dashboard is reachable at ``/w/{id}`` the
        instant it returns. The team-forming + first round (``seed_team`` +
        ``run_workspace``, which DO drive ``runtime.generate_*``) are deferred to
        :meth:`build_initial`, run on a background thread so the create request
        never blocks the event loop. The record is born ``status="building"``.

        Construction still happens under the build lock because ``Glimi()`` re-points
        the kernel's process-global store to this workspace (last-wins); the lock
        keeps that atomic with id allocation. The heavy build is scoped separately.

        ``ws_id`` / ``created_at`` / ``persist=False`` are used by restore-on-startup
        to rebuild a persisted workspace with its original id + timestamp.
        ``auto_run`` / ``context`` / ``backlog`` / ``max_rounds`` are the
        autonomous-loop brief, stamped onto the Workspace.
        """
        owner_name = (name or "Owner").strip() or "Owner"
        goal = (goal or "").strip() or "Plan the launch of a new app / service"
        with self._lock:
            g = Glimi(backend=_USER_BACKEND, owner_name=owner_name)
            if ws_id is None:
                ws_id = self._next_user_id()
            elif ws_id.startswith("ws") and ws_id[2:].isdigit():
                self._seq = max(self._seq, int(ws_id[2:]))  # keep new ids ahead of restored ones
            ws = Workspace(id=ws_id, glimi=g, title=goal, goal=goal, kind="user",
                           created_at=created_at or _now_utc_iso(),
                           status="building",
                           auto_run=bool(auto_run), context=context or "",
                           backlog=list(backlog or []),
                           max_rounds=max(1, min(int(max_rounds or 5), 10)))
            self.register(ws)
        if persist:
            _persist_ws_meta(ws_id, owner_name, goal, ws.created_at,
                             auto_run=ws.auto_run, context=ws.context,
                             backlog=ws.backlog, max_rounds=ws.max_rounds)
        return ws

    def build_initial(self, ws: "Workspace", *, on_event=None) -> None:
        """Run the deferred team-forming + first round for a freshly-created record.

        The slow half of create: ``seed_team`` (manager proposes a goal-appropriate
        roster on a real backend; echo → the deterministic default 3) then
        ``run_workspace`` (the full interaction topology + first deliverable). Both
        drive ``runtime.generate_*``, so they MUST run scoped to ``ws`` — routed
        through :meth:`run_in_ws` (the same per-workspace scoping lock chat turns +
        the auto-run driver use), which re-points the kernel globals at this ws and
        serializes against every other build/turn.

        Idempotent + double-run-guarded: only runs while ``status=="building"`` and
        the team isn't already seeded; flips ``status`` to ``"ready"`` on success
        (``"error"`` on failure) so the UI's "forming…" banner clears. ``on_event``
        streams the team-forming + each turn live to connected chat WebSockets.
        """
        # Double-run guard: only the building→ready transition runs the build.
        if ws.status != "building":
            return
        owner_name = ws.glimi.owner.name()
        goal = ws.goal

        def _build():
            # Skip if the team is already seeded (a racing/duplicate call).
            try:
                if ws.store.get_agent("coordinator"):
                    return
            except Exception:
                pass
            # Manager proposes a goal-appropriate roster (real backend), else the
            # DEFAULT researcher/builder/critic (echo → deterministic). Runs AFTER
            # run_in_ws has pointed the kernel globals at this ws's store.
            seed_team(ws.glimi, goal, owner_name)
            # Real interaction topology → a genuine interaction web for the goal,
            # streaming each turn live via on_event (the create's "watch it build").
            run_workspace(ws.glimi, owner_name, goal, on_event=on_event)

        try:
            self.run_in_ws(ws, _build)
            ws.status = "ready"
        except Exception:  # noqa: BLE001 — a failed build must not crash the thread
            ws.status = "error"
            raise

    def create(self, name: str, goal: str, *, ws_id: Optional[str] = None,
               created_at: Optional[str] = None, persist: bool = True,
               auto_run: bool = False, context: str = "",
               backlog: Optional[list] = None, max_rounds: int = 5) -> Workspace:
        """Create a workspace AND run its first round INLINE (blocking).

        The synchronous convenience used by restore-on-startup and the tests: it
        creates the record then immediately runs the deferred build on the calling
        thread, so the returned Workspace is fully ``"ready"``. On the echo backend
        this is instant + deterministic (restore reproduces each workspace exactly).

        The live, non-blocking create path (``POST /api/workspaces``) instead calls
        :meth:`create_record` + :meth:`build_initial` on a background thread, so the
        request returns immediately and the build streams to the dashboard.
        """
        ws = self.create_record(
            name, goal, ws_id=ws_id, created_at=created_at, persist=persist,
            auto_run=auto_run, context=context, backlog=backlog, max_rounds=max_rounds,
        )
        self.build_initial(ws)
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

# ── per-workspace dashboard endpoint shapes (mirror glimi/dashboard/app.py) ───

def _snapshot_payload(reader: DashboardReader) -> dict:
    """``/api/snapshot`` in the rich dashboard shape. This is exactly the canonical
    :func:`glimi.dashboard.enrich_snapshot` — the kernel ships the enricher so the
    SAME shape (graph / KPIs / agent cards) renders for the kernel demo, a
    workspace, and any ``KernelStore`` population. Kept as a thin alias so the
    route reads naturally and a workspace-specific tweak would have one home."""
    return _enrich_snapshot(reader)


def _demo_ws_supervisors(payload: dict) -> list:
    """데모 전용 — 워크스페이스 팀을 감시하는 supervisor 세트(합성 관찰 데이터).
    실제 supervisor 런타임 와이어링은 추후. 팀 협업·산출물·진행을 감시하는 모습으로
    '관찰성' 레이어를 시연한다 (커뮤니티 demo_mock 과 같은 발상)."""
    import time as _time
    agents = payload.get("agents") or []
    aids = [a.get("id") for a in agents if a.get("id")]
    channels = payload.get("channels") or []
    now = int(_time.time())
    sups = [
        {
            "name": "orchestrator", "kind": "system",
            "display_name": "오케스트레이터", "icon": "🧭",
            "active": True, "intervening": False,
            "target_agents": aids[:4],
            "last_action": "크리틱↔빌더 리스크 토론이 길어짐 — 팀장에게 정리·합의 신호를 보냄",
            "seconds_since_action": now % 40 + 4,
        },
        {
            "name": "deliverable", "kind": "system",
            "display_name": "산출물 감수", "icon": "📋",
            "active": True, "intervening": (now // 19) % 2 == 0,
            "target_agents": [a for a in aids if "critic" in a or "coordinator" in a][:2] or aids[:1],
            "last_action": "'하루칸' 출시 계획 초안 점검 — 런칭 게이트(온보딩 검증) 항목 누락 없는지 확인",
            "seconds_since_action": now % 50 + 6,
        },
        {
            "name": "commitment", "kind": "system",
            "display_name": "진행 추적", "icon": "🤝",
            "active": True, "intervening": False,
            "target_agents": [a for a in aids if "builder" in a][:2] or aids[:1],
            "last_action": "D-2 '깨끗한 기기 온보딩 테스트' 액션 추적 — 담당 빌더에게 리마인드 검토",
            "seconds_since_action": now % 55 + 8,
        },
    ]
    aname = {a.get("id"): a.get("name", "") for a in agents}
    alias = {"owner": "오너", "approvals": "승인", "team": "팀 전체", "system": "시스템"}

    def _lbl(nm: str) -> str:
        rest = nm
        for pre in ("internal-", "group-", "dm-", "mgr-"):
            if nm.startswith(pre):
                rest = nm[len(pre):]
                break
        if rest in alias:
            return alias[rest]
        return "·".join(aname.get(t, alias.get(t, t)) for t in rest.split("-"))

    chat_chs = [c for c in channels
                if (c.get("name") or "").startswith(("internal-", "group-", "mgr-"))]
    acts = [
        "방금 오간 협업 메시지 분석 — 합의 진행 중, 개입 불필요",
        "한 명의 제안이 묻힘 — 팀장에게 끌어올릴지 검토",
        "리스크 지적이 반복됨 — 결정 라운드로 넘길 타이밍 감지",
        "조용 — 다음 산출물 라운드 대기",
    ]
    for i, c in enumerate(chat_chs[:4]):
        nm = c.get("name") or ""
        parts = [p for p in (c.get("participants") or []) if p]
        sups.append({
            "name": f"chat.{nm}", "kind": "chat",
            "display_name": f"대화 · {_lbl(nm)}", "icon": "💬",
            "active": i < 2, "intervening": i == 0,
            "target_agents": parts[:3],
            "last_action": acts[i % len(acts)],
            "seconds_since_action": (now + i * 9) % 50 + 3,
        })
    return sups


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


def _make_ws_broadcaster(ws: "Workspace", loop: "asyncio.AbstractEventLoop"):
    """Build the driver's ``on_event`` sink: fan a frame out to every chat WS
    currently subscribed to ``ws``.

    The driver runs on its own background thread, so we can't ``await`` here — we
    hop onto the SERVER's event loop (``loop``, the one the WebSockets live on) with
    ``run_coroutine_threadsafe`` and ``send_json`` to each subscriber. A send to a
    dead socket is swallowed + the socket dropped, so a disconnect can't stall the
    loop. Best-effort: never raises into the driver, and tolerates zero subscribers
    (a headless run / a test with no chat WS connected just no-ops)."""
    def _emit(frame: dict) -> None:
        if loop is None or not ws._subscribers:
            return
        async def _fanout():
            for sock in list(ws._subscribers):
                try:
                    await sock.send_json(frame)
                except Exception:
                    ws._subscribers.discard(sock)
        try:
            asyncio.run_coroutine_threadsafe(_fanout(), loop)
        except Exception:
            pass
    return _emit


class _DriverHandle:
    """A thread-backed handle for one autonomous owner-driver run.

    The driver loop is an ``async`` coroutine, but anchoring it to a request's
    asyncio task (``asyncio.create_task``) is fragile — anyio/Starlette cancel
    child tasks when the spawning request scope exits, so the loop would die the
    moment ``/auto/start`` returns. Instead we run it on a dedicated DAEMON THREAD
    with its own private event loop, fully decoupled from any request and from the
    server's loop. Cancellation flows through the shared ``threading.Event`` the
    driver already polls (set by ``cancel()``); ``done()`` reports liveness so
    ``driver_running`` + ``/auto/status`` work without touching the server loop."""

    def __init__(self, coro_factory, cancel: "threading.Event", *, name: str) -> None:
        self._cancel = cancel
        self._done = threading.Event()

        def _runner() -> None:
            try:
                asyncio.run(coro_factory())
            finally:
                self._done.set()

        self._thread = threading.Thread(target=_runner, daemon=True, name=name)
        self._thread.start()

    def done(self) -> bool:
        return self._done.is_set()

    def cancel(self) -> None:
        # The driver polls this Event at the top of each round + during its sleep,
        # so setting it stops a sleeping or between-rounds driver promptly.
        try:
            self._cancel.set()
        except Exception:
            pass


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


def _internal_pair_label(ws: "Workspace", channel: str,
                         names: dict[str, str]) -> str:
    """Friendly ``"A ↔ B"`` label for a behind-the-scenes ``internal-<a>-<b>``
    channel, resolving each side's display name.

    Robust to ids that themselves contain hyphens (e.g. ``culture-coach``, or the
    coordinator side of ``internal-coordinator-<sid>``): prefer the channel's two
    STORED participants over a naive hyphen split (which can't tell ``a-b-c-d``
    apart). Falls back to the participants from the store, then to a naive split of
    the channel id, then to the raw id — always returns a non-empty label."""
    def _name(aid: str) -> str:
        return names.get(aid) or (ws.store.get_agent(aid) or {}).get("name") or aid

    # Preferred: the two stored participants (unambiguous for multi-hyphen ids).
    try:
        parts = [p for p in (ws.store.get_channel_participants(channel) or []) if p]
    except Exception:
        parts = []
    if len(parts) >= 2:
        return f"{_name(parts[0])} ↔ {_name(parts[1])}"

    # Fallback: naive split of internal-<a>-<b> into two tokens (best-effort).
    rest = channel[len("internal-"):] if channel.startswith("internal-") else channel
    bits = rest.split("-", 1)
    if len(bits) == 2 and bits[0] and bits[1]:
        return f"{_name(bits[0])} ↔ {_name(bits[1])}"
    return channel


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
    # ``agent_type`` lets the shared chat.js section the list (coordinator=mgr →
    # Coordinator/Managers; specialists=persona → Team).
    for a in reader.agents():
        aid = a.get("id")
        if not aid:
            continue
        dm_channel = f"dm-{aid}"
        out.append({
            "channel": dm_channel,
            "kind": "dm",
            "agent_id": aid,
            "agent_type": a.get("type", ""),
            "name": a.get("name") or aid,
            "type": a.get("type", ""),
            "postable": True,
            "avatar_url": f"/w/{ws.id}/api/avatar?id={aid}&v={_ASSET_VER}",
            "last": _last_preview(store, dm_channel, owner_ids, names, owner_name),
        })
    # group-* (multi-agent rooms) + internal-* (specialist↔specialist A2A — the team
    # talking to each other, the workspace's whole point). internal-* is READ-ONLY
    # ("Behind the scenes"): the owner watches, doesn't post.
    try:
        overview = store.get_channel_overview()
    except Exception:
        overview = []
    for c in overview:
        name = c.get("channel") or ""
        if name.startswith("group-"):
            out.append({
                "channel": name, "kind": "group", "agent_id": None,
                "agent_type": "group", "name": name, "type": "group",
                "postable": True, "avatar_url": None,
                "last": _last_preview(store, name, owner_ids, names, owner_name),
            })
        elif name.startswith("internal-"):
            # ``internal-owner`` is the read-only channel where the autonomous owner
            # logs its per-round reasoning (the "owner thinking" the web shows). Give
            # it a friendly display name + tooltip. Every OTHER internal-* is a
            # behind-the-scenes pair (coordinator↔specialist delegation or
            # specialist↔specialist A2A); show a friendly "A ↔ B" label resolved from
            # its two agent ids, not the raw channel id.
            is_owner_review = (name == _OWNER_REVIEW_CHANNEL)
            disp = (_OWNER_REVIEW_NAME if is_owner_review
                    else _internal_pair_label(ws, name, names))
            out.append({
                "channel": name, "kind": "internal", "agent_id": None,
                "agent_type": "internal", "name": disp, "type": "internal",
                "postable": False, "avatar_url": None,
                "tooltip": _OWNER_REVIEW_TOOLTIP if is_owner_review else None,
                "last": _last_preview(store, name, owner_ids, names, owner_name),
            })
    return out


def _chat_history(
    ws: "Workspace", channel: str, limit: int, before_id: Optional[int] = None,
) -> list[dict]:
    """Recent messages for ``channel`` (ASC by id), display-ready. Mirrors
    ``chat.py._channel_history``: resolves speaker → display name + is_user,
    passes the store's compact ``reactions`` summary through, and resolves a
    reply quote from the loaded window when the parent is present.

    ``before_id`` pages backwards (the ``limit`` messages older than that id) for
    "load older on scroll-to-top".
    """
    reader = ws.reader()
    store = ws.store
    owner_name, owner_ids = _chat_owner(reader)
    names = _agent_name_map(reader)

    try:
        rows = store.get_recent_messages(channel, limit, before_id=before_id)
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
        "caps_json": json.dumps(_WS_CAPS_DEMO if ws.id == "demo" else _WS_CAPS),
        "community_chrome": False,
        "app_name": "Glimi Workspace",
        "brand_logo": True,            # show the Glimi logo (served at /logo) in the brand
        "active_tab": active_tab,
        "user": None,
        "community_id": None,           # workspace uses api_base, not ?community=
        "community_name": ws.title,
        "language": lang,
        "read_only": (ws.kind == "demo"),  # public demo = browse-only; user workspaces are writable
        "asset_v": _ASSET_VER,
        "chat_channel": "dm-coordinator",
        "chat_agent": "coordinator",
        "chat_user": owner_name or "You",
        "refresh_ms": refresh_ms or "",
    }
    resp = _TEMPLATES.TemplateResponse(request, "dashboard/_core.html", ctx)
    resp.headers["Cache-Control"] = "no-store"
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

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        # The autonomous driver runs on its OWN background thread (decoupled from any
        # request scope), but its WS fan-out must post onto the SERVER's event loop.
        # Capture it here so the broadcaster always targets the live socket loop.
        app.state.main_loop = asyncio.get_running_loop()
        yield

    app = FastAPI(title="Glimi Workspace — Server", docs_url=None, redoc_url=None,
                  lifespan=_lifespan)
    app.state.registry = reg
    app.state.main_loop = None  # the server's event loop, captured at startup (WS fan-out)

    # All dashboard assets (css / js) are the canonical Core ones, served from the
    # installed glimi[dashboard] package — single source, no workspace-local copy.
    app.mount("/static", StaticFiles(directory=str(_DASH_STATIC)), name="static")

    if with_demo:
        _install_demo(reg, interval=demo_interval)
    if not _DEMO_ONLY:
        _restore_user_workspaces(reg)  # bring back user-created workspaces across restarts

    def _require(ws_id: str) -> Workspace:
        ws = reg.get(ws_id)
        if ws is None:
            raise HTTPException(status_code=404, detail=f"unknown workspace: {ws_id}")
        return ws

    # ── home ──────────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, lang: str = "ko"):
        """Workspace picker + (unless demo-only) create form. Renders the SHARED
        ``_demo_list.html`` so this page is visually identical to the Community demo
        list. Korean-primary; ``?lang=en`` switches."""
        lang = (lang or "ko").lower()
        if lang not in ("ko", "en"):
            lang = "ko"
        EN = (lang == "en")
        items = []
        for c in reg.cards():
            metas = ([f"{c['agents']} teammates", f"{c['channels']} channels"] if EN
                     else [f"팀원 {c['agents']}명", f"채널 {c['channels']}개"])
            items.append({
                "href": f"/w/{c['id']}",
                "title": c["title"],
                "desc": c.get("goal") or "",
                "is_demo": (c["kind"] == "demo"),
                "building": (c.get("status") == "building"),
                "avatars": c.get("avatars") or [],
                "more": max(0, c["agents"] - len(c.get("avatars") or [])),
                "metas": metas,
            })
        create = None
        if not _DEMO_ONLY:
            create = {
                "action": "/api/workspaces",
                "heading": "Or start your own" if EN else "직접 만들어 보기",
                "lede": ("Name yourself, give a goal, and a new team led by a team lead forms around it."
                         if EN else "이름을 적고 목표를 정하면, 팀장이 이끄는 새 팀이 그 주위로 꾸려져요."),
                "name_label": "Your name" if EN else "이름",
                "name_ph": "e.g. Alex" if EN else "예: 지수",
                "goal_label": "Goal" if EN else "목표",
                "goal_ph": ("e.g. Plan the launch of a new app, Karukan"
                            if EN else "예: 신규 앱 '하루칸' 출시 기획"),
                "submit": "Create workspace" if EN else "워크스페이스 만들기",
            }
        ctx = {
            "request": request, "lang": lang, "user": None, "asset_v": _ASSET_VER,
            "brand": "Glimi Workspace",
            "brand_sub": ("specialist teams on one Glimi Core" if EN
                          else "하나의 Glimi Core 위에서 움직이는 전문가 팀"),
            "lede": ("Set a goal and a team forms around it — a team lead splits the work among "
                     "teammates who research, build, and review, and they share ideas to bring back "
                     "a result. Open a demo below to watch it. No login needed." if EN
                     else "목표를 주면 그 주위로 팀이 꾸려집니다 — 조사·구현·검토를 맡은 팀원들에게 팀장이 일을 "
                          "나눠 주고, 서로 의견을 주고받으며 결과를 가져와요. 아래 데모를 열면 그 과정을 볼 수 "
                          "있어요. 로그인도 필요 없어요."),
            "items": items,
            "create": create,
        }
        resp = _TEMPLATES.TemplateResponse(request, "_demo_list.html", ctx)
        resp.headers["Cache-Control"] = "no-store"
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
        """Create a workspace from a form (browser) or JSON (API) — NON-BLOCKING.

        The record (its ``Glimi`` + store) is created IMMEDIATELY and this returns
        right away (``status="building"``); the team-forming + first round run on a
        dedicated background thread (``reg.build_initial`` via a ``_DriverHandle``,
        the same machinery /auto/start uses), streaming each turn to connected chat
        WebSockets via the per-ws broadcaster. So ``/w/{id}`` is reachable instantly
        and the dashboard shows the team forming + the first round progressing LIVE,
        exactly like watching an auto-run — not a link handed back after it finishes.

        Form submits get a 303 redirect to the new dashboard (the page then opens its
        chat WS and watches the build); JSON callers get the card with ``status``.
        """
        if _DEMO_ONLY:  # public showcase: only the seeded demo exists, no creation
            raise HTTPException(status_code=403, detail="this is a demo-only instance")
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

        # 1) Create the record immediately (cheap: Glimi construction only) so the
        #    dashboard is reachable at /w/{id} the instant we return.
        ws = reg.create_record(name, goal)

        # 2) Run the team-forming + first round on a background DAEMON THREAD,
        #    streaming each turn to connected chat WebSockets via the per-ws
        #    broadcaster (fan-out targets the SERVER's event loop, where the sockets
        #    live). The fan-out tolerates zero subscribers, so the build runs whether
        #    or not the owner's page has connected its WS yet.
        server_loop = app.state.main_loop
        broadcaster = _make_ws_broadcaster(ws, server_loop)

        async def _build():
            try:
                broadcaster({"type": "auto", "phase": "building", "ws": ws.id})
                reg.build_initial(ws, on_event=broadcaster)
                broadcaster({"type": "auto", "phase": "ready", "ws": ws.id})
            except Exception as e:  # noqa: BLE001 — never crash the build thread
                broadcaster({"type": "auto", "phase": "error", "message": str(e)})

        ws._build_task = _DriverHandle(_build, threading.Event(),
                                       name=f"glimi-ws-build-{ws.id}")

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
        return _render_core(request, ws, active_tab="overview")

    @app.get("/w/{ws_id}/agent/{agent_id}", response_class=HTMLResponse)
    def agent_detail(ws_id: str, agent_id: str, request: Request) -> HTMLResponse:
        """Full per-agent detail page (status / profile / relationships / memory /
        reasoning / recent chat) — the canonical ``agent_detail.html`` shared with
        Community, retargeted via api_base=/w/{id} and read-only (no model switch)."""
        ws = _require(ws_id)
        lang = (request.query_params.get("lang") or "ko").lower()
        if lang not in ("ko", "en"):
            lang = "ko"
        ctx = {
            "request": request,
            "user": None,
            "agent_id": agent_id,
            "community_id": None,            # workspace routes via api_base, not ?community=
            "community_name": ws.title,
            "language": lang,
            "api_base": f"/w/{ws.id}",
            "back_url": f"/w/{ws.id}",
            "interactive": False,            # read-only: model switch hidden
            "asset_v": _ASSET_VER,
        }
        resp = _TEMPLATES.TemplateResponse(request, "agent_detail.html", ctx)
        resp.headers["Cache-Control"] = "no-store"
        return resp

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
    def w_chat_history(
        ws_id: str, channel: str = "", limit: int = 50, before_id: int = 0,
    ) -> JSONResponse:
        ws = _require(ws_id)
        channel = (channel or "").strip()
        if not channel:
            return JSONResponse({"error": "missing channel"}, status_code=400)
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            before = int(before_id)
        except (TypeError, ValueError):
            before = 0
        before = before if before > 0 else None
        return JSONResponse({
            "channel": channel,
            "messages": _chat_history(ws, channel, limit, before_id=before),
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
        read_only = (ws.kind == "demo")
        await websocket.accept()
        loop = asyncio.get_event_loop()
        # Subscribe this socket to the workspace's live fan-out so the autonomous
        # owner-driver's per-turn + lifecycle frames stream to it (the same channel
        # the demo's scripted loop can use). Discarded on disconnect (finally).
        ws._subscribers.add(websocket)
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
                        "message": "둘러보기 전용 데모예요. 직접 워크스페이스를 만들면 팀과 대화할 수 있어요.",
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
        finally:
            ws._subscribers.discard(websocket)

    # ── autonomous owner-driver (auto-run) ──────────────────────────────────
    # The work-clone analogue of the Community's autonomous social-sim: the
    # owner-agent runs the goal → review → assign loop a human normally runs by hand.
    # COST-safe: opt-in (auto_run default False), bounded by max_rounds AND the
    # monthly budget cap (enforced inside the loop), externally cancellable, and on
    # the offline echo backend entirely free. The public Demo NEVER starts a live
    # run (kind=='demo' → 403); it showcases the loop via demo.py's scripted unfold.
    @app.post("/w/{ws_id}/auto/start", response_model=None)
    async def auto_start(ws_id: str, request: Request):
        """Arm + launch the autonomous owner-driver loop for a writable workspace.

        Body JSON (all optional): ``{context?:str, backlog?:[str]|str,
        max_rounds?:int}`` — ``max_rounds`` is clamped 1..10 (default 5). Gating:
        404 unknown · 403 on the read-only Demo · 409 if a run is already in flight.
        The loop streams its turns + lifecycle frames to every connected chat WS via
        the per-ws fan-out; budget is enforced INSIDE the loop (not at start) so a
        mid-run cap trips cleanly."""
        ws = _require(ws_id)
        if ws.kind == "demo":
            raise HTTPException(status_code=403, detail="demo is read-only")
        if ws.driver_running:
            raise HTTPException(status_code=409, detail="auto-run already in progress")

        body = {}
        try:
            if "application/json" in (request.headers.get("content-type", "")):
                body = await request.json()
        except Exception:
            body = {}
        context = str((body or {}).get("context", "") or "").strip()
        backlog_raw = (body or {}).get("backlog", None)
        if isinstance(backlog_raw, str):
            backlog = [ln.strip() for ln in backlog_raw.splitlines() if ln.strip()]
        elif isinstance(backlog_raw, list):
            backlog = [str(x).strip() for x in backlog_raw if str(x).strip()]
        else:
            backlog = []
        try:
            max_rounds = max(1, min(int((body or {}).get("max_rounds", ws.max_rounds or 5)), 10))
        except (TypeError, ValueError):
            max_rounds = 5

        # Stamp + persist the brief (so the toggle + brief survive a restart; the
        # loop itself is not auto-resumed on boot — see _restore_user_workspaces).
        ws.auto_run = True
        ws.context = context
        ws.backlog = backlog
        ws.max_rounds = max_rounds
        ws.rounds_run = 0
        ws.driver_reason = ""
        _persist_ws_meta(ws.id, ws.glimi.owner.name(), ws.goal, ws.created_at,
                         auto_run=True, context=context, backlog=backlog,
                         max_rounds=max_rounds)

        # The WS fan-out targets the SERVER's event loop (captured at startup), NOT
        # the driver thread's private loop — that's where the chat WebSockets live.
        server_loop = app.state.main_loop
        cancel = threading.Event()
        ws._driver_cancel = cancel
        broadcaster = _make_ws_broadcaster(ws, server_loop)

        # run_scoped routes every kernel-touching step through the registry's
        # per-workspace scoping lock (reg.run_in_ws) so the global-singleton WRITE
        # path stays serialized + pointed at THIS workspace, exactly like a chat turn.
        def _run_scoped(fn):
            return reg.run_in_ws(ws, fn)

        async def _drive():
            try:
                result = await drive_workspace(
                    ws.glimi, goal=ws.goal, context=ws.context, backlog=ws.backlog,
                    owner_name=ws.glimi.owner.name(), max_rounds=ws.max_rounds,
                    on_event=broadcaster, cancel=cancel, run_scoped=_run_scoped,
                )
                ws.rounds_run = int(result.get("rounds", 0))
                ws.driver_reason = str(result.get("stopped_reason", "") or "")
            except Exception as e:  # noqa: BLE001 — never crash the server thread
                ws.driver_reason = "error"
                broadcaster({"type": "auto", "phase": "error", "message": str(e)})
            finally:
                ws.auto_run = False
                ws._driver_task = None
                # Persist the toggle back OFF so a restart doesn't show it armed.
                _persist_ws_meta(ws.id, ws.glimi.owner.name(), ws.goal, ws.created_at,
                                 auto_run=False, context=ws.context,
                                 backlog=ws.backlog, max_rounds=ws.max_rounds)

        # Run on a dedicated daemon thread (decoupled from the request scope) so the
        # loop survives /auto/start returning; cancellation flows via the Event.
        ws._driver_task = _DriverHandle(
            _drive, cancel, name=f"glimi-ws-driver-{ws.id}",
        )
        return JSONResponse({"ok": True, "running": True, "max_rounds": max_rounds})

    @app.post("/w/{ws_id}/auto/stop", response_model=None)
    async def auto_stop(ws_id: str):
        """Cancel the autonomous loop (idempotent). 404 unknown; otherwise always
        ``{ok:true, running:false}`` — sets the cancel Event + cancels the task so a
        sleeping or mid-round driver stops promptly."""
        ws = _require(ws_id)
        if ws._driver_cancel is not None:
            try:
                ws._driver_cancel.set()
            except Exception:
                pass
        t = ws._driver_task
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
        ws.auto_run = False
        _persist_ws_meta(ws.id, ws.glimi.owner.name(), ws.goal, ws.created_at,
                         auto_run=False, context=ws.context,
                         backlog=ws.backlog, max_rounds=ws.max_rounds)
        return JSONResponse({"ok": True, "running": False})

    @app.get("/w/{ws_id}/auto/status")
    def auto_status(ws_id: str) -> JSONResponse:
        """Reflect the loop's state so the toggle can restore on page load + poll:
        ``{running, auto_run, rounds_run, reason, max_rounds}``. Reads ws fields; no
        lock needed."""
        ws = _require(ws_id)
        return JSONResponse({
            "running": ws.driver_running,
            "auto_run": bool(ws.auto_run),
            "rounds_run": int(ws.rounds_run),
            "reason": ws.driver_reason or None,
            "max_rounds": int(ws.max_rounds),
        })

    # ── dynamic team: add a specialist (owner-initiated) ────────────────────
    # The OWNER-initiated path to grow the team — the owner IS the approver by
    # calling this, so no HITL gate (the gate is for the MANAGER's mid-run ask,
    # which the driver auto-approves under auto-run). The add is serialized +
    # scoped through reg.run_in_ws so the global-singleton WRITE path stays pointed
    # at THIS workspace (every ws reuses ids like 'coordinator'). The new agent
    # appears in /chat/channels immediately; it SPEAKS from the next round/turn on
    # (run_round re-derives the live roster each call).
    @app.post("/w/{ws_id}/team/add", response_model=None)
    async def team_add(ws_id: str, request: Request):
        """Add a specialist to a writable workspace's team.

        Body JSON: ``{role:str, name?:str, persona?:str, role_keyword?:str}`` —
        ``role`` is the role id (slugged server-side). Gating: 404 unknown · 403 on
        the read-only Demo · 400 missing role · 409 on a reserved/collision id.
        Returns the new agent's card on success.
        """
        ws = _require(ws_id)
        if ws.kind == "demo":
            raise HTTPException(status_code=403, detail="demo is read-only")
        body = {}
        try:
            if "application/json" in (request.headers.get("content-type", "")):
                body = await request.json()
        except Exception:
            body = {}
        role = str((body or {}).get("role", "") or "").strip().lower()
        # Slug the role id the same way the manager's proposal is sanitized.
        role = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in role)
        role = "-".join(p for p in role.split("-") if p)[:32]
        if not role:
            raise HTTPException(status_code=400, detail="role required")
        if role in RESERVED_IDS:
            raise HTTPException(status_code=409, detail=f"reserved id: {role}")
        if ws.store.get_agent(role):
            raise HTTPException(status_code=409, detail=f"id already on team: {role}")
        name = str((body or {}).get("name", "") or "").strip() or role
        persona = str((body or {}).get("persona", "") or "").strip()
        if not persona:
            persona = f"{name} is the team's {role}."
        role_keyword = str((body or {}).get("role_keyword", "") or "").strip() or role

        def _add():
            return add_team_member(ws.glimi, role, name, persona, role_keyword)

        ok = await asyncio.get_event_loop().run_in_executor(
            None, reg.run_in_ws, ws, _add)
        if not ok:
            raise HTTPException(status_code=409, detail=f"could not add: {role}")
        return JSONResponse({
            "id": role,
            "name": name,
            "agent_type": "persona",
            "avatar_url": f"/w/{ws.id}/api/avatar?id={role}&v={_ASSET_VER}",
            "channel": f"dm-{role}",
        })

    # ── per-workspace chat avatars (workspace layer; no kernel image field) ──
    @app.get("/w/{ws_id}/api/avatar")
    def w_avatar(ws_id: str, id: str = "") -> Response:
        """Role-based emoji avatar (inline SVG). The workspace team is functional
        (Coordinator/Researcher/Builder/Critic + any manager-proposed role) — no
        persona/anime portraits. A dynamic role's emoji comes from its stored
        ``role_keyword`` when its id isn't a known role. Always 200."""
        ws = _require(ws_id)
        role_keyword = ""
        try:
            role_keyword = (ws.store.get_agent(id) or {}).get("role_keyword") or ""
        except Exception:
            role_keyword = ""
        return Response(content=_avatar_svg(id, role_keyword), media_type="image/svg+xml",
                        headers={"Cache-Control": "no-cache"})

    @app.get("/w/{ws_id}/api/snapshot")
    def w_snapshot(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        payload = _snapshot_payload(ws.reader())
        # The shared dashboard hero reads community_meta.name → inject the workspace
        # title so the Overview/graph heading isn't blank (enrich_snapshot leaves it none).
        cm = dict(payload.get("community_meta") or {})
        cm["name"] = ws.title
        # 클라이언트 SERVER_LANG → JS chrome 언어. demo-en = 영문 미러, 나머지 = KO 1차.
        cm["language"] = "en" if ws.id == "demo-en" else "ko"
        payload["community_meta"] = cm
        payload["community_id"] = ws.id
        # 데모 워크스페이스만: 팀을 감시하는 supervisor 뷰(합성 관찰 데이터) 노출.
        if ws.id == "demo":
            payload["supervisors"] = _demo_ws_supervisors(payload)
        # Surface the initial build status so the chat UI can show a "team forming…"
        # banner the instant a workspace is created (cleared when status flips to
        # "ready" — the create build runs in the background, streaming live).
        payload["build"] = {
            "status": ("building" if ws.building else ws.status),
            "building": ws.building,
        }
        # Surface the autonomous-loop state so the chat UI can restore the toggle
        # on load (writable workspaces only — the demo is read-only).
        payload["auto"] = {
            "running": ws.driver_running,
            "auto_run": bool(ws.auto_run),
            "rounds_run": int(ws.rounds_run),
            "reason": ws.driver_reason or None,
            "max_rounds": int(ws.max_rounds),
            "writable": (ws.kind != "demo"),
        }
        return JSONResponse(payload)

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
        # dashboard.js reads d.tool_calls → must match the community envelope, not a bare list.
        return JSONResponse({"tool_calls": ws.reader().tool_timeline(limit=limit)})

    @app.get("/w/{ws_id}/api/usage")
    def w_usage(ws_id: str) -> JSONResponse:
        ws = _require(ws_id)
        return JSONResponse(ws.reader().usage())

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
    # English mirror demo (/w/demo-en) — faithful EN of the KO demo, same shape.
    try:
        g_en = _demo_en.build()
        ws_en = Workspace(id="demo-en", glimi=g_en, title="Launch-plan demo",
                          goal=_demo_en.GOAL, kind="demo")
        reg.register(ws_en)
        threading.Thread(
            target=_demo_en.activity_loop, args=(g_en, threading.Event(), interval),
            daemon=True, name="glimi-workspace-server-demo-en",
        ).start()
    except Exception as e:  # noqa: BLE001 — EN demo is best-effort; never break startup
        print(f"[ws] demo-en install skipped: {e}")
    # Daemon thread → dies with the process; server lifetime == demo lifetime, so
    # we don't expose a stop handle.
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
    print("=" * 64 + "\n")
    uvicorn.run(app, host=host, port=port, **uvicorn_kwargs)
    return 0
