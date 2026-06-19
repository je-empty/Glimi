"""DashboardReader — a store-driven, read-only view over an agent population.

This is the data layer of the (future) ``glimi[dashboard]`` extra. It renders
*any* agent population from a :class:`~glimi.store.KernelStore` alone — no web
server, no Community, no Discord, no app-specific assumptions. Point it at any
store and read back agents, per-agent detail (profile + 5-layer memory + facts +
relationships + channels + coverage), channels, and a connection-graph snapshot.

Design constraints (this is P1.0 of the dashboard decoupling):
- **Zero-dep**: pure stdlib + the kernel's own ``KernelStore``. No FastAPI /
  Jinja / pydantic / Discord / ``src.*`` imports. The web layer lands in a later
  slice.
- **Domain-neutral**: no channel-name conventions are assumed (no ``dm-`` /
  ``mgr-`` / ``internal-`` special-casing). The reader works on whatever the
  store exposes.
- **Degrades gracefully**: every method returns best-effort data (empty lists /
  ``None``) and never raises on a sparse or partly-populated store.

The output *shapes* mirror ``src/core/monitor.py`` (the app's current read layer)
where reasonable, so a renderer written against monitor can be pointed here with
minimal change — but the reader itself only ever reads through the store.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..store import KernelStore

# The 5-layer memory system: L0 raw → L1/L2/L3 rollups → (facts are a separate
# semantic layer). We surface levels 0–4 so a future level slots in without a
# code change; sparse stores simply return empty lists for the unused ones.
_MEMORY_LEVELS = (0, 1, 2, 3, 4)


def _safe(fn, default):
    """Call ``fn()`` and return its result, or ``default`` on any failure.

    The store contract says implementations should not raise, but third-party
    stores may be incomplete; the dashboard must never crash on one bad method.
    """
    try:
        return fn()
    except Exception:  # noqa: BLE001 — best-effort read layer
        return default


class DashboardReader:
    """Read-only dashboard data, sourced entirely from a :class:`KernelStore`.

    Construct with a store and call the read methods::

        from glimi import Glimi
        from glimi.dashboard import DashboardReader

        g = Glimi(backend="echo", owner_name="Owner")
        g.add_agent("alice", name="Alice", persona="...")
        g.reply("alice", "hi", channel="room")

        r = DashboardReader(g.store)
        r.agents()              # population overview
        r.agent_detail("alice") # profile + memory + facts + relationships + channels
        r.channels()            # channel overview + participants
        r.snapshot()            # {"agents", "channels", "relationships"} for the graph
    """

    def __init__(self, store: KernelStore) -> None:
        if store is None:
            raise ValueError("DashboardReader requires a KernelStore instance")
        self.store = store

    # ── agents ─────────────────────────────────────────────────────────
    def agents(self) -> list[dict]:
        """All agents with basic display info.

        Each entry: ``id``, ``name``, ``type``, ``status``, ``model_override``,
        ``emotion``, ``intensity``, ``last_active``. Sorted mgr → creator → dev →
        persona, then by id — matching ``monitor.get_agents`` ordering without
        importing it.
        """
        rows = _safe(lambda: self.store.list_agents(), []) or []
        out = [self._agent_basic(a) for a in rows]
        out.sort(key=lambda a: (self._type_rank(a.get("type")), a.get("id") or ""))
        return out

    def _agent_basic(self, agent: dict) -> dict:
        aid = agent.get("id", "")
        emotion, intensity = self._emotion(aid, agent)
        override = _safe(lambda: self.store.get_agent_model_override(aid), None)
        if override is None:
            override = agent.get("model_override")
        return {
            "id": aid,
            "name": agent.get("name") or aid,
            "type": agent.get("type") or "",
            "status": agent.get("status") or "",
            "model_override": override,
            "emotion": emotion,
            "intensity": intensity,
            "last_active": agent.get("last_active") or "",
        }

    def _emotion(self, agent_id: str, agent: dict) -> tuple[Optional[str], Optional[int]]:
        """Current emotion/intensity — prefer the store's typed accessor, fall
        back to the agent row's columns. Returns ``(emotion, intensity)``."""
        res = _safe(lambda: self.store.get_agent_emotion(agent_id), None)
        if res:
            try:
                emotion, intensity = res
                return emotion, intensity
            except Exception:  # noqa: BLE001
                pass
        return (agent.get("current_emotion"),
                agent.get("emotion_intensity"))

    @staticmethod
    def _type_rank(agent_type: Optional[str]) -> int:
        return {"mgr": 0, "creator": 1, "dev": 2}.get(agent_type or "", 3)

    # ── agent detail ───────────────────────────────────────────────────
    def agent_detail(self, agent_id: str) -> dict:
        """Full per-agent view, sourced from the store.

        Mirrors the shape of ``monitor.get_agent_detail`` where reasonable:
        profile basics + the 5-layer memory breakdown + pinned memories +
        semantic facts + relationships + the agent's channels + per-channel
        memory coverage. Returns ``{"error": "agent not found"}`` for an
        unknown id (never raises).
        """
        agent = _safe(lambda: self.store.get_agent(agent_id), None)
        if not agent:
            return {"error": "agent not found", "id": agent_id}

        basic = self._agent_basic(agent)

        channels = _safe(
            lambda: self.store.get_agent_channels(agent_id, exclude_channel="",
                                                  include_mgr=True),
            [],
        ) or []
        coverage = _safe(
            lambda: self.store.get_memory_coverage(agent_id, exclude_channel=""),
            {},
        ) or {}

        memories_by_channel = self._memories_by_channel(agent_id, channels)
        pinned = _safe(lambda: self.store.get_pinned_memories(agent_id), []) or []
        facts = _safe(lambda: self.store.get_facts(agent_id), []) or []
        relationships = self._relationships_for(agent_id)

        detail = dict(basic)
        detail.update({
            "channels": channels,
            "memory_coverage": coverage,
            "memories_by_channel": memories_by_channel,
            "pinned_memories": pinned,
            "facts": facts,
            "relationships": relationships,
        })
        return detail

    def _memories_by_channel(self, agent_id: str, channels: list[dict]) -> dict[str, dict]:
        """Per-channel 5-layer memory breakdown.

        ``{channel: {"levels": {0: [...], 1: [...], ...}, "latest": {level: row}}}``.
        Only channels the agent has spoken in (from ``get_agent_channels``) are
        probed — no channel-naming assumptions.
        """
        out: dict[str, dict] = {}
        for ch in channels:
            name = ch.get("channel") if isinstance(ch, dict) else None
            if not name:
                continue
            levels: dict[int, list[dict]] = {}
            latest: dict[int, dict] = {}
            for level in _MEMORY_LEVELS:
                rows = _safe(
                    lambda lv=level: self.store.get_memories(agent_id, name, lv),
                    [],
                ) or []
                if rows:
                    levels[level] = rows
                last = _safe(
                    lambda lv=level: self.store.get_latest_memory(agent_id, name, lv),
                    None,
                )
                if last:
                    latest[level] = last
            if levels or latest:
                out[name] = {"levels": levels, "latest": latest}
        return out

    def _relationships_for(self, agent_id: str) -> list[dict]:
        """This agent's relationships, probed pairwise against every other agent
        and the registered owner(s).

        The :class:`KernelStore` ABC exposes only ``get_relationship(a, b)`` for a
        specific pair (no bulk listing), so the reader probes all candidate pairs.
        That keeps it store-agnostic at the cost of O(n) lookups per agent.
        """
        out: list[dict] = []
        others = self._relationship_candidates(exclude=agent_id)
        for other_id in others:
            rel = _safe(lambda o=other_id: self.store.get_relationship(agent_id, o), None)
            if rel is None:
                rel = _safe(lambda o=other_id: self.store.get_relationship(o, agent_id), None)
            if not rel:
                continue
            out.append({
                "other_id": other_id,
                "type": rel.get("type") or "",
                "intimacy": rel.get("intimacy_score", 0) or 0,
                "dynamics": rel.get("dynamics") or "",
            })
        out.sort(key=lambda r: r.get("intimacy", 0), reverse=True)
        return out

    def _relationship_candidates(self, exclude: Optional[str] = None) -> list[str]:
        """All ids that could be the other end of a relationship: every agent +
        every registered user (owner)."""
        ids: list[str] = []
        for a in (_safe(lambda: self.store.list_agents(), []) or []):
            aid = a.get("id")
            if aid and aid != exclude:
                ids.append(aid)
        for u in (_safe(lambda: self.store.list_users(), []) or []):
            uid = u.get("id")
            if uid and uid != exclude and uid not in ids:
                ids.append(uid)
        return ids

    # ── channels ───────────────────────────────────────────────────────
    def channels(self) -> list[dict]:
        """Channel overview from the store, with participants where available.

        Each entry carries whatever ``get_channel_overview`` exposes (channel,
        msg_count, speakers, last_active, …) plus a ``participants`` list filled
        from ``get_channel_participants`` when the overview omits it.
        """
        rows = _safe(lambda: self.store.get_channel_overview(), []) or []
        out: list[dict] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            entry = dict(r)
            name = entry.get("channel")
            if name and not entry.get("participants"):
                entry["participants"] = _safe(
                    lambda n=name: self.store.get_channel_participants(n), [],
                ) or []
            out.append(entry)
        return out

    # ── observability — tool-call timeline + LLM usage ──────────────────
    def tool_timeline(self, *, limit: int = 50,
                      agent_id: Optional[str] = None) -> list[dict]:
        """Recent tool-call invocations (newest first), from the store.

        Each entry: ``created_at``, ``agent_id``, ``agent_type``, ``channel``,
        ``tool_name``, ``args_json``, ``result_preview``, ``ok`` (0/1),
        ``latency_ms``. A store without the observability method degrades to ``[]``
        (the base ``recent_tool_calls`` returns ``[]``; ``_safe`` guards anyway).
        """
        return _safe(
            lambda: self.store.recent_tool_calls(limit=limit, agent_id=agent_id),
            [],
        ) or []

    def usage(self, *, community: Optional[str] = None) -> dict:
        """LLM usage/cost view (today + this-month-to-date), from the store.

        Boundary math (first-of-month / start-of-today, UTC) lives here so the
        route stays thin. ``$`` figures are only meaningful on the API-key/SDK
        path — CLI rows are recorded with ``estimated=1`` and ``estimated_count``
        surfaces how many of the counted calls are estimates, so the UI can label
        them "est." A store without usage methods degrades to zeroed dicts.
        """
        since_month = _first_of_month_utc()
        since_today = _start_of_today_utc()
        spend_month = _safe(
            lambda: self.store.usage_spend(since=since_month, community=community), {}
        ) or {}
        spend_today = _safe(
            lambda: self.store.usage_spend(since=since_today, community=community), {}
        ) or {}
        by_agent = _safe(
            lambda: self.store.usage_by_agent(since=since_month, community=community), []
        ) or []
        return {
            "as_of": _now_utc_iso(),
            "pricing_as_of": _pricing_as_of(),
            "spend_today": float(spend_today.get("total_cost", 0.0) or 0.0),
            "spend_month": float(spend_month.get("total_cost", 0.0) or 0.0),
            "call_count_today": int(spend_today.get("call_count", 0) or 0),
            "call_count_month": int(spend_month.get("call_count", 0) or 0),
            "estimated_count_month": int(spend_month.get("estimated_count", 0) or 0),
            "input_tokens_month": int(spend_month.get("input_tokens", 0) or 0),
            "output_tokens_month": int(spend_month.get("output_tokens", 0) or 0),
            "avg_latency_ms": int(spend_month.get("avg_latency_ms", 0) or 0),
            "by_agent": by_agent,
        }

    # ── connection graph ───────────────────────────────────────────────
    def snapshot(self) -> dict:
        """A single-call snapshot for the connection graph.

        ``{"agents": [...], "channels": [...], "relationships": [...]}`` where
        each relationship is an undirected edge ``{source, target, type,
        intimacy, dynamics}`` derived from the store. Nodes (agents/channels)
        carry the same display info as :meth:`agents` / :meth:`channels`.
        """
        agents = self.agents()
        channels = self.channels()
        relationships = self._all_relationships()
        return {
            "agents": agents,
            "channels": channels,
            "relationships": relationships,
        }

    def _all_relationships(self) -> list[dict]:
        """Every relationship edge in the population, deduped (undirected).

        Probes each unordered pair of relationship candidates via
        ``get_relationship``. Edge shape: ``source``/``target`` (graph-friendly)
        plus ``intimacy``/``type``/``dynamics`` (matching the app's relationship
        row fields).
        """
        candidates = self._relationship_candidates()
        seen: set[frozenset] = set()
        edges: list[dict] = []
        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                key = frozenset((a, b))
                if key in seen:
                    continue
                rel = _safe(lambda: self.store.get_relationship(a, b), None)
                if rel is None:
                    rel = _safe(lambda: self.store.get_relationship(b, a), None)
                if not rel:
                    continue
                seen.add(key)
                edges.append({
                    "source": rel.get("agent_a") or a,
                    "target": rel.get("agent_b") or b,
                    "type": rel.get("type") or "",
                    "intimacy": rel.get("intimacy_score", 0) or 0,
                    "dynamics": rel.get("dynamics") or "",
                })
        edges.sort(key=lambda e: e.get("intimacy", 0), reverse=True)
        return edges


# ── usage view helpers (UTC boundary math + pricing metadata) ───────────

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_of_month_utc() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0,
                       microsecond=0).isoformat()


def _start_of_today_utc() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _pricing_as_of() -> str:
    """The pricing table's as-of date, surfaced so stale rates are visible.

    Best-effort: the pricing module is kernel-side and dependency-free, but the
    reader keeps its zero-dep promise by tolerating its absence."""
    try:
        from ..llm.pricing import PRICING_AS_OF
        return PRICING_AS_OF
    except Exception:
        return ""


# ── Public reader-derived helpers (apps consume these from glimi.dashboard) ────
# Pure (store reads only, no web deps), so they live in the zero-dep reader and
# can be imported without pulling the FastAPI layer. Apps that build their own
# chat/snapshot payloads (e.g. Glimi Workspace) use these instead of reaching
# into the private dashboard.app internals.
def owner_info(reader: "DashboardReader") -> tuple[str, list[str]]:
    """(display name, list of user ids) for the registered owner(s). Best-effort:
    returns ``("Owner", [])`` when the store exposes no users."""
    try:
        users = reader.store.list_users() or []
    except Exception:
        users = []
    ids = [u.get("id") for u in users if u.get("id")]
    name = "Owner"
    if users:
        name = users[0].get("name") or users[0].get("id") or "Owner"
    return name, ids


def channel_detail(reader: "DashboardReader", name: str) -> dict:
    """Participants + recent messages for a channel, read straight off the store.
    Domain-neutral and best-effort."""
    store = reader.store
    try:
        participants = store.get_channel_participants(name) or []
    except Exception:
        participants = []
    try:
        messages = store.get_recent_messages(name, limit=300) or []
    except Exception:
        messages = []
    return {
        "name": name,
        "participants": participants,
        "messages": messages,
        "message_count": len(messages),
    }


def _channel_kind(nm: str) -> str:
    if nm.startswith("dm-"):
        return "dm"
    if nm.startswith("internal-"):
        return "internal-group"
    if nm.startswith("mgr-"):
        return "mgr"
    return "group"


def enrich_snapshot(reader: "DashboardReader") -> dict:
    """The canonical ``/api/snapshot`` shape the rich dashboard.js reads.

    ``DashboardReader.snapshot()`` is the minimal kernel view (agents / channels /
    relationships / owner). The polished dashboard expects a few presentation
    fields on top — per-agent live flags + emoji/mbti/age/intensity_band defaults,
    channel kind/participant_count, an aggregated ``recent_messages`` feed, plus
    ``meta`` / ``bot`` / ``total_messages``. This helper fills them from the store
    so the SAME dashboard renders any ``KernelStore`` population (kernel demo,
    Glimi Workspace). Pure/zero-dep and best-effort — never raises on a sparse
    store. Apps with a richer native snapshot (Community's ``monitor.snapshot()``)
    don't need this; they already produce the full shape.
    """
    snap = reader.snapshot()
    owner_name, owner_ids = owner_info(reader)
    owner_id_set = set(owner_ids)
    try:
        names = {a["id"]: (a.get("name") or a["id"]) for a in reader.agents()}
    except Exception:
        names = {}

    def _band(i):
        return "high" if i >= 7 else ("mid" if i >= 4 else "low")

    agents = [{
        "thinking": False, "speaking": False,
        "thinking_channel": "", "speaking_channel": "",
        "thinking_seconds": 0, "speaking_seconds": 0,
        "model": a.get("model") or "claude-haiku-4-5",
        "provider": a.get("provider") or "claude",
        "emoji": a.get("emoji") or "",          # avoid 'undefined' in the emoji badge
        "intensity_band": a.get("intensity_band") or _band(a.get("intensity") or 0),
        "mbti": a.get("mbti") or "",
        "age": a.get("age") or "",
        **a,
    } for a in snap.get("agents", [])]

    channels, total = [], 0
    for c in snap.get("channels", []):
        nm = c.get("channel") or c.get("name") or ""
        mc = c.get("msg_count", 0) or 0
        total += mc
        parts = c.get("participants", []) or []
        channels.append({
            "name": nm, "channel": nm,   # "channel" kept for back-compat consumers
            "participants": parts, "participant_count": len(parts),
            "status": "idle", "msg_count": mc, "kind": _channel_kind(nm),
            "internal": nm.startswith("internal-"),
            "last_ts": c.get("last_active", ""), "last_ago": "", "last_speaker": "",
        })

    # recent_messages — last few across channels (oldest → newest).
    recent = []
    for c in channels:
        try:
            for m in (reader.store.get_recent_messages(c["name"], limit=8) or []):
                spk = m.get("speaker") or m.get("agent_id") or ""
                recent.append({
                    "channel": c["name"],
                    "speaker": spk,
                    "display_name": owner_name if spk in owner_id_set else names.get(spk, spk),
                    "is_user": spk in owner_id_set,
                    "text": m.get("text") or m.get("content") or "",
                    "timestamp": m.get("timestamp") or m.get("ts") or "",
                })
        except Exception:
            pass
    recent.sort(key=lambda m: m.get("timestamp") or "")
    recent = recent[-40:]

    return {
        **snap,
        "agents": agents,
        "channels": channels,
        "recent_messages": recent,
        "total_messages": total,
        "owner_name": owner_name,
        "owner_ids": owner_ids,
        "meta": {"user_name": owner_name},
        "bot": {"bot_alive": True},
        "events": [], "scenes": [], "supervisors": [],
        "community_id": None,
        "community_meta": {"language": "en"},
        "dev_pending_count": 0, "dev_visible": False,
    }
