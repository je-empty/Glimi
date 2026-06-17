"""In-memory :class:`~glimi.store.KernelStore` — zero-dependency, in-process.

Every abstract method is implemented faithfully against plain dicts/lists, so
``runtime.generate_response`` runs end-to-end with no database. It mirrors the
shapes the SQLite adapter returns (hydrated rows: ``related_entities`` / ``knows``
are real lists, not JSON strings) so the kernel reads them the same way.

Scope: it is a correct, self-contained reference store for quick-starts, tests,
and examples — not a production store (no persistence, no indexes, single
process, not thread-safe beyond a coarse lock). Apps with a real DB implement
their own :class:`~glimi.store.KernelStore`.

Timestamps are stored as UTC-aware ISO strings per project convention
(``datetime.now(timezone.utc).isoformat()``).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..store import KernelStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class InMemoryKernelStore(KernelStore):
    """A complete, in-process KernelStore backed by Python data structures."""

    # Default new-relationship intimacy (mirrors the app's 0–100 scale, "어색~친구").
    DEFAULT_INTIMACY = 30
    # log_message dedup window (matches the SQLite store's 30s turn-level guard).
    DEDUP_WINDOW_SEC = 30

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._agents: dict[str, dict] = {}
        self._users: dict[str, dict] = {}
        # conversations: append-only list of rows with autoincrement id.
        self._conversations: list[dict] = []
        self._conv_seq = 0
        # channels: channel -> {participants, status, max_turns, current_turn, created_at}
        self._channels: dict[str, dict] = {}
        # memories: list of hydrated rows with autoincrement id.
        self._memories: list[dict] = []
        self._mem_seq = 0
        # facts: list of rows; valid_to=None means current.
        self._facts: list[dict] = []
        self._fact_seq = 0
        # relationships keyed by (agent_a, agent_b).
        self._relationships: dict[tuple[str, str], dict] = {}
        self._rel_history: list[dict] = []
        self._rel_hist_seq = 0
        self._events: list[dict] = []
        self._event_seq = 0
        self._message_hooks: list = []
        # reactions: list of rows {id, message_id, actor_id, emoji, created_at}.
        self._reactions: list[dict] = []
        self._react_seq = 0
        # observability: tool calls + usage records (mirror SqliteKernelStore so
        # the dashboard's tool-timeline / usage panels work on the in-memory store
        # too — used by examples/dashboard_demo and the Workspace demo).
        self._tool_calls: list[dict] = []
        self._toolcall_seq = 0
        self._usage: list[dict] = []
        self._usage_seq = 0

    # ── helpers for the convenience facade (not part of the ABC) ──────
    def upsert_agent(self, agent_id: str, *, name: str, agent_type: str = "persona",
                     current_emotion: str = "평온", emotion_intensity: int = 5,
                     model_override: Optional[str] = None, **extra) -> dict:
        """Register / update an agent row. Used by the high-level facade."""
        with self._lock:
            row = self._agents.get(agent_id, {})
            row.update({
                "id": agent_id,
                "type": agent_type,
                "name": name,
                "status": extra.get("status", "active"),
                "current_emotion": current_emotion,
                "emotion_intensity": emotion_intensity,
                "model_override": model_override,
                "last_active": _now_iso(),
            })
            row.setdefault("created_at", _now_iso())
            for k, v in extra.items():
                row.setdefault(k, v)
            self._agents[agent_id] = row
            return dict(row)

    def upsert_user(self, user_id: str, *, name: str, **extra) -> dict:
        with self._lock:
            row = self._users.get(user_id, {})
            row.update({"id": user_id, "name": name})
            row.setdefault("created_at", _now_iso())
            for k, v in extra.items():
                row[k] = v
            self._users[user_id] = row
            return dict(row)

    def set_relationship(self, agent_a: str, agent_b: str, *, rel_type: str = "friend",
                         intimacy: Optional[int] = None, dynamics: str = "") -> None:
        with self._lock:
            self._relationships[(agent_a, agent_b)] = {
                "id": len(self._relationships) + 1,
                "agent_a": agent_a,
                "agent_b": agent_b,
                "type": rel_type,
                "intimacy_score": self.DEFAULT_INTIMACY if intimacy is None else int(intimacy),
                "dynamics": dynamics,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }

    # ── conversation engine ───────────────────────────────────────────
    def set_channel_status(self, channel: str, status: str, max_turns: int = 0) -> None:
        with self._lock:
            ch = self._channels.setdefault(channel, self._new_channel(channel))
            ch["status"] = status
            ch["max_turns"] = max_turns

    def increment_channel_turn(self, channel: str) -> int:
        with self._lock:
            ch = self._channels.setdefault(channel, self._new_channel(channel))
            ch["current_turn"] = (ch.get("current_turn") or 0) + 1
            return ch["current_turn"]

    def get_recent_messages(self, channel: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = [m for m in self._conversations if m["channel"] == channel]
            out = [dict(r) for r in rows[-limit:]]
            self._attach_reactions(out)
            return out

    def get_messages_by_range(self, channel: str, after_id: int, limit: int = 15) -> list[dict]:
        with self._lock:
            rows = [m for m in self._conversations
                    if m["channel"] == channel and m["id"] > after_id]
            rows.sort(key=lambda r: r["id"])
            return [dict(r) for r in rows[:limit]]

    # ── reactions / replies / threads ─────────────────────────────────
    def add_reaction(self, message_id: int, actor_id: str, emoji: str) -> bool:
        with self._lock:
            # Parent must exist (mirror FK ON).
            if not any(m["id"] == message_id for m in self._conversations):
                return False
            # UNIQUE(message_id, actor_id, emoji) — idempotent add.
            for r in self._reactions:
                if (r["message_id"] == message_id and r["actor_id"] == actor_id
                        and r["emoji"] == emoji):
                    return False
            self._react_seq += 1
            self._reactions.append({
                "id": self._react_seq, "message_id": message_id,
                "actor_id": actor_id, "emoji": emoji, "created_at": _now_iso(),
            })
            return True

    def remove_reaction(self, message_id: int, actor_id: str, emoji: str) -> None:
        with self._lock:
            self._reactions = [
                r for r in self._reactions
                if not (r["message_id"] == message_id and r["actor_id"] == actor_id
                        and r["emoji"] == emoji)
            ]

    def get_reactions(self, message_id: int) -> list[dict]:
        with self._lock:
            rows = [r for r in self._reactions if r["message_id"] == message_id]
            rows.sort(key=lambda r: r["id"])
            return [{"emoji": r["emoji"], "actor_id": r["actor_id"],
                     "created_at": r["created_at"]} for r in rows]

    def get_reactions_for(self, message_ids: list[int]) -> dict[int, list[dict]]:
        if not message_ids:
            return {}
        idset = set(message_ids)
        with self._lock:
            rows = [r for r in self._reactions if r["message_id"] in idset]
            rows.sort(key=lambda r: r["id"])
            out: dict[int, list[dict]] = {}
            for r in rows:
                out.setdefault(r["message_id"], []).append(
                    {"emoji": r["emoji"], "actor_id": r["actor_id"],
                     "created_at": r["created_at"]})
            return out

    def set_reply(self, message_id: int, reply_to: int) -> None:
        with self._lock:
            thread_root = None
            for m in self._conversations:
                if m["id"] == reply_to:
                    thread_root = m.get("thread_root") or m["id"]
                    break
            for m in self._conversations:
                if m["id"] == message_id:
                    m["reply_to"] = reply_to
                    m["thread_root"] = thread_root
                    return

    def get_thread(self, root_id: int, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = [m for m in self._conversations
                    if m.get("thread_root") == root_id or m["id"] == root_id]
            rows.sort(key=lambda r: r["id"])
            out = [dict(r) for r in rows[:limit]]
            self._attach_reactions(out)
            return out

    @staticmethod
    def _summarize_reactions(rows: list[dict]) -> list[dict]:
        by_emoji: dict[str, dict] = {}
        order: list[str] = []
        for r in rows:
            e = r["emoji"]
            slot = by_emoji.get(e)
            if slot is None:
                slot = {"emoji": e, "count": 0, "actors": []}
                by_emoji[e] = slot
                order.append(e)
            slot["count"] += 1
            slot["actors"].append(r["actor_id"])
        return [by_emoji[e] for e in order]

    def _attach_reactions(self, rows: list[dict]) -> None:
        """Fold a compact ``reactions`` summary onto each row (caller holds the lock)."""
        if not rows:
            return
        ids = {r["id"] for r in rows if r.get("id") is not None}
        grouped: dict[int, list[dict]] = {}
        for rr in sorted(self._reactions, key=lambda r: r["id"]):
            if rr["message_id"] in ids:
                grouped.setdefault(rr["message_id"], []).append(rr)
        for r in rows:
            r["reactions"] = self._summarize_reactions(grouped.get(r.get("id"), []))

    # ── runtime ───────────────────────────────────────────────────────
    def get_agent(self, agent_id: str) -> Optional[dict]:
        with self._lock:
            row = self._agents.get(agent_id)
            return dict(row) if row else None

    def list_agents(self, agent_type: Optional[str] = None) -> list[dict]:
        with self._lock:
            rows = self._agents.values()
            if agent_type:
                rows = [r for r in rows if r.get("type") == agent_type]
            return [dict(r) for r in rows]

    def get_channel_participants(self, channel: str) -> list[str]:
        with self._lock:
            ch = self._channels.get(channel)
            return list(ch["participants"]) if ch else []

    def get_channel_overview(self) -> list[dict]:
        with self._lock:
            stats: dict[str, dict] = {}
            for m in self._conversations:
                ch = m["channel"]
                s = stats.setdefault(ch, {
                    "channel": ch, "msg_count": 0, "speakers": set(),
                    "last_active": None, "first_active": None,
                })
                s["msg_count"] += 1
                s["speakers"].add(m["speaker"])
                ts = m["timestamp"]
                if s["last_active"] is None or ts > s["last_active"]:
                    s["last_active"] = ts
                if s["first_active"] is None or ts < s["first_active"]:
                    s["first_active"] = ts
            result: dict[str, dict] = {}
            for ch, meta in self._channels.items():
                base = stats.get(ch, {
                    "channel": ch, "msg_count": 0, "speakers": set(),
                    "last_active": None, "first_active": None,
                })
                base["channel"] = ch
                base["participants"] = list(meta["participants"])
                result[ch] = base
            for ch, base in stats.items():
                if ch not in result:
                    base["participants"] = []
                    result[ch] = base
            out = []
            for base in result.values():
                base = dict(base)
                base["speakers"] = len(base["speakers"]) if isinstance(base.get("speakers"), set) else base.get("speakers", 0)
                out.append(base)
            out.sort(key=lambda x: x.get("last_active") or "", reverse=True)
            return out

    def get_agent_model_override(self, agent_id: str) -> Optional[str]:
        with self._lock:
            row = self._agents.get(agent_id)
            return row.get("model_override") if row else None

    def log_message(self, channel: str, speaker: str, message: str,
                    emotion: Optional[str] = None,
                    reply_to: Optional[int] = None) -> Optional[int]:
        with self._lock:
            # Turn-level dedup: skip identical channel/speaker/message within window.
            # Returns the EXISTING row id (not None) so a broadcast frame stays addressable.
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.DEDUP_WINDOW_SEC)
            for m in reversed(self._conversations):
                if m["channel"] != channel or m["speaker"] != speaker:
                    continue
                if m["message"] != message:
                    continue
                dt = _parse_iso(m["timestamp"])
                if dt and dt > cutoff:
                    return m["id"]  # duplicate within window
            # Reply → denormalize thread_root (parent's thread_root or parent id).
            thread_root = None
            if reply_to is not None:
                for m in self._conversations:
                    if m["id"] == reply_to:
                        thread_root = m.get("thread_root") or m["id"]
                        break
                else:
                    reply_to = None  # unknown parent → plain message
            self._conv_seq += 1
            new_id = self._conv_seq
            self._conversations.append({
                "id": new_id,
                "channel": channel,
                "speaker": speaker,
                "message": message,
                "context_emotion": emotion,
                "reply_to": reply_to,
                "thread_root": thread_root,
                "timestamp": _now_iso(),
            })
            if speaker in self._agents:
                self._agents[speaker]["last_active"] = _now_iso()
            hooks = list(self._message_hooks)
        # Fire hooks outside the lock (mirrors app: failures don't break logging).
        for hook in hooks:
            try:
                hook(channel, speaker, message)
            except Exception as e:  # noqa: BLE001
                print(f"[InMemoryKernelStore hook] {getattr(hook, '__name__', hook)}: {e}")
        return new_id

    def add_message_hook(self, fn) -> None:
        with self._lock:
            if fn not in self._message_hooks:
                self._message_hooks.append(fn)

    # ── runtime — higher-level ─────────────────────────────────────────
    def get_recent_events(self, agent_id: str, event_types: list[str],
                          window_sec: int, limit: int = 8) -> list[dict]:
        if not event_types:
            return []
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_sec)
            rows = []
            for e in self._events:
                if e["event_type"] not in event_types:
                    continue
                parts = (e.get("participants") or "").split(",")
                if not parts or parts[0] != agent_id:
                    continue
                dt = _parse_iso(e["timestamp"])
                if dt and dt < cutoff:
                    continue
                rows.append(dict(e))
            rows.sort(key=lambda r: r["id"], reverse=True)
            return rows[:limit]

    def get_agent_channels(self, agent_id: str, exclude_channel: str,
                           include_mgr: bool) -> list[dict]:
        with self._lock:
            last_id: dict[str, int] = {}
            for m in self._conversations:
                if m["speaker"] != agent_id:
                    continue
                ch = m["channel"]
                if ch == exclude_channel:
                    continue
                if not include_mgr and ch.startswith("mgr"):
                    continue
                if m["id"] > last_id.get(ch, 0):
                    last_id[ch] = m["id"]
            rows = [{"channel": ch, "last_id": lid} for ch, lid in last_id.items()]
            rows.sort(key=lambda r: r["last_id"], reverse=True)
            return rows

    def get_memory_coverage(self, agent_id: str, exclude_channel: str) -> dict[str, int]:
        with self._lock:
            cov: dict[str, int] = {}
            for m in self._memories:
                if m["agent_id"] != agent_id or m["channel"] == exclude_channel:
                    continue
                mid = m.get("msg_id_to") or 0
                if mid > cov.get(m["channel"], 0):
                    cov[m["channel"]] = mid
            return cov

    # ── memory ────────────────────────────────────────────────────────
    def get_agent_by_name(self, name: str) -> Optional[dict]:
        with self._lock:
            for row in self._agents.values():
                if row.get("name") == name:
                    return dict(row)
            return None

    def get_relationship(self, agent_a: str, agent_b: str) -> Optional[dict]:
        with self._lock:
            row = self._relationships.get((agent_a, agent_b))
            return dict(row) if row else None

    def get_relationship_history(self, agent_a: str, agent_b: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = [
                dict(h) for h in self._rel_history
                if (h["agent_a"] == agent_a and h["agent_b"] == agent_b)
                or (h["agent_a"] == agent_b and h["agent_b"] == agent_a)
            ]
            rows.sort(key=lambda r: r["id"], reverse=True)
            return rows[:limit]

    def update_intimacy(self, agent_a: str, agent_b: str, delta: int) -> None:
        with self._lock:
            row = self._relationships.get((agent_a, agent_b))
            if not row:
                return
            row["intimacy_score"] = max(0, min(100, (row.get("intimacy_score") or 0) + delta))
            row["updated_at"] = _now_iso()

    def add_relationship_delta(self, agent_a: str, agent_b: str, delta_type: str,
                               from_state: Optional[str] = None, to_state: Optional[str] = None,
                               reason: Optional[str] = None, source_channel: Optional[str] = None,
                               source_memory_id: Optional[int] = None) -> int:
        with self._lock:
            self._rel_hist_seq += 1
            self._rel_history.append({
                "id": self._rel_hist_seq,
                "agent_a": agent_a, "agent_b": agent_b, "delta_type": delta_type,
                "from_state": from_state, "to_state": to_state, "reason": reason,
                "source_channel": source_channel, "source_memory_id": source_memory_id,
                "created_at": _now_iso(),
            })
            return self._rel_hist_seq

    def get_memories(self, agent_id: str, channel: str, level: int, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = [m for m in self._memories
                    if m["agent_id"] == agent_id and m["channel"] == channel and m["level"] == level]
            # Mirror SQLite: ORDER BY created_at DESC LIMIT, then reversed → oldest-first.
            rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            rows = rows[:limit]
            rows.reverse()
            return [self._hydrate(r) for r in rows]

    def get_latest_memory(self, agent_id: str, channel: str, level: int) -> Optional[dict]:
        with self._lock:
            rows = [m for m in self._memories
                    if m["agent_id"] == agent_id and m["channel"] == channel and m["level"] == level]
            if not rows:
                return None
            rows.sort(key=lambda r: (r.get("msg_id_to") or 0, r["id"]))
            return self._hydrate(rows[-1])

    def get_pinned_memories(self, agent_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = [m for m in self._memories
                    if m["agent_id"] == agent_id and m.get("is_pinned")]
            rows.sort(key=lambda r: (r.get("importance") or 0, r["created_at"]), reverse=True)
            return [self._hydrate(r) for r in rows[:limit]]

    def add_memory(self, agent_id: str, channel: str, level: int, content: str,
                   msg_id_from: Optional[int] = None, msg_id_to: Optional[int] = None,
                   msg_count: int = 0, mem_type: Optional[str] = None,
                   related_entities: Optional[list] = None, knows: Optional[list] = None,
                   importance: int = 5, is_pinned: bool = False,
                   parent_memory_id: Optional[int] = None,
                   related_agent_id: Optional[str] = None) -> int:
        with self._lock:
            self._mem_seq += 1
            self._memories.append({
                "id": self._mem_seq,
                "agent_id": agent_id, "channel": channel, "level": level,
                "content": content, "mem_type": mem_type,
                "related_entities": list(related_entities) if related_entities else [],
                "knows": list(knows) if knows else [],
                "importance": importance, "is_pinned": 1 if is_pinned else 0,
                "parent_memory_id": parent_memory_id,
                "msg_id_from": msg_id_from, "msg_id_to": msg_id_to,
                "msg_count": msg_count, "related_agent_id": related_agent_id,
                "created_at": _now_iso(), "last_accessed_at": _now_iso(),
            })
            return self._mem_seq

    def set_pin(self, memory_id: int, pinned: bool = True) -> None:
        with self._lock:
            for m in self._memories:
                if m["id"] == memory_id:
                    m["is_pinned"] = 1 if pinned else 0
                    return

    def touch_memory_access(self, memory_ids: list[int]) -> None:
        with self._lock:
            ids = set(memory_ids)
            for m in self._memories:
                if m["id"] in ids:
                    m["last_accessed_at"] = _now_iso()

    def count_messages_after(self, channel: str, after_id: int) -> int:
        with self._lock:
            return sum(1 for m in self._conversations
                       if m["channel"] == channel and m["id"] > after_id)

    def get_facts(self, agent_id: str, subject: Optional[str] = None,
                  include_invalid: bool = False, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = [f for f in self._facts if f["agent_id"] == agent_id]
            if subject:
                rows = [f for f in rows if f["subject"] == subject]
            if not include_invalid:
                rows = [f for f in rows if f.get("valid_to") is None]
            rows.sort(key=lambda r: (r.get("importance") or 0, r["created_at"]), reverse=True)
            return [dict(r) for r in rows[:limit]]

    def add_fact(self, agent_id: str, subject: str, predicate: str, object_value: str,
                 source_channel: Optional[str] = None, source_memory_id: Optional[int] = None,
                 confidence: float = 1.0, importance: int = 5) -> int:
        with self._lock:
            # Supersession: close the current valid fact for same (subject, predicate).
            existing = None
            for f in reversed(self._facts):
                if (f["agent_id"] == agent_id and f["subject"] == subject
                        and f["predicate"] == predicate and f.get("valid_to") is None):
                    existing = f
                    break
            if existing is not None:
                if existing["object"] == object_value:
                    return existing["id"]
                existing["valid_to"] = _now_iso()
            self._fact_seq += 1
            self._facts.append({
                "id": self._fact_seq,
                "agent_id": agent_id, "subject": subject, "predicate": predicate,
                "object": object_value, "source_channel": source_channel,
                "source_memory_id": source_memory_id,
                "confidence": float(confidence),
                "importance": max(1, min(10, int(importance))),
                "valid_from": _now_iso(), "valid_to": None,
                "created_at": _now_iso(), "last_accessed_at": _now_iso(),
            })
            return self._fact_seq

    def list_users(self) -> list[dict]:
        with self._lock:
            return [dict(u) for u in self._users.values()]

    # ── memory — higher-level ──────────────────────────────────────────
    def set_relationship_dynamics(self, agent_a: str, agent_b: str, dynamics: str) -> None:
        with self._lock:
            row = self._relationships.get((agent_a, agent_b))
            if row:
                row["dynamics"] = dynamics
                row["updated_at"] = _now_iso()

    def get_agent_emotion(self, agent_id: str) -> Optional[tuple[str, int]]:
        with self._lock:
            row = self._agents.get(agent_id)
            if not row:
                return None
            return (row.get("current_emotion"), row.get("emotion_intensity") or 5)

    def set_agent_emotion(self, agent_id: str, emotion: str, intensity: int) -> None:
        with self._lock:
            row = self._agents.get(agent_id)
            if row:
                row["current_emotion"] = emotion
                row["emotion_intensity"] = intensity

    def get_uncovered_memories(self, agent_id: str, channel: str, source_level: int) -> list[dict]:
        with self._lock:
            target_level = source_level + 1
            covered = [m for m in self._memories
                       if m["agent_id"] == agent_id and m["channel"] == channel
                       and m["level"] == target_level]
            source = [m for m in self._memories
                      if m["agent_id"] == agent_id and m["channel"] == channel
                      and m["level"] == source_level]
            if source_level == 1:
                last_covered = max((m.get("msg_id_to") or 0 for m in covered), default=0)
                rows = [m for m in source if (m.get("msg_id_to") or 0) > last_covered]
                rows.sort(key=lambda r: (r.get("msg_id_to") or 0))
            else:
                last_covered = max((m["id"] for m in covered), default=0)
                rows = [m for m in source if m["id"] > last_covered]
                rows.sort(key=lambda r: r["id"])
            return [self._hydrate(r) for r in rows]

    def get_memories_across_channels(self, agent_id: str, exclude_channel: str,
                                     levels: list[int], limit: int) -> list[dict]:
        if not levels:
            return []
        with self._lock:
            rows = [m for m in self._memories
                    if m["agent_id"] == agent_id and m["channel"] != exclude_channel
                    and m["level"] in levels]
            rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return [self._hydrate(r) for r in rows[:limit]]

    def get_recent_messages_across_channels(self, agent_id: str, exclude_channel: str,
                                            within_minutes: int, limit: int) -> list[dict]:
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
            rows = []
            for m in self._conversations:
                if m["speaker"] != agent_id or m["channel"] == exclude_channel:
                    continue
                dt = _parse_iso(m["timestamp"])
                if dt and dt < cutoff:
                    continue
                rows.append({"channel": m["channel"], "message": m["message"],
                             "timestamp": m["timestamp"], "_id": m["id"]})
            rows.sort(key=lambda r: r["timestamp"], reverse=True)
            for r in rows:
                r.pop("_id", None)
            return rows[:limit]

    def search_memories(self, agent_id: str, entity: Optional[str] = None,
                        query: Optional[str] = None, time_range_days: Optional[int] = None,
                        limit: int = 20) -> list[dict]:
        with self._lock:
            rows = [m for m in self._memories if m["agent_id"] == agent_id]
            if entity:
                rows = [m for m in rows if entity in (m.get("related_entities") or [])]
            if query:
                q = query.lower()
                rows = [m for m in rows
                        if q in (m.get("content") or "").lower()
                        or q in (m.get("mem_type") or "").lower()]
            if time_range_days:
                cutoff = datetime.now(timezone.utc) - timedelta(days=time_range_days)
                rows = [m for m in rows
                        if (_parse_iso(m["created_at"]) or cutoff) >= cutoff]
            rows.sort(key=lambda r: (r.get("importance") or 0, r["created_at"]), reverse=True)
            limit = max(1, min(50, int(limit)))
            return [self._hydrate(r) for r in rows[:limit]]

    def get_memory(self, memory_id: int) -> Optional[dict]:
        with self._lock:
            for m in self._memories:
                if m["id"] == memory_id:
                    return self._hydrate(m)
            return None

    def get_memory_stats(self, agent_id: str, channel: str) -> dict:
        with self._lock:
            total = sum(1 for m in self._conversations if m["channel"] == channel)

            def _cnt(level: int) -> int:
                return sum(1 for m in self._memories
                           if m["agent_id"] == agent_id and m["channel"] == channel
                           and m["level"] == level)

            pinned = sum(1 for m in self._memories
                         if m["agent_id"] == agent_id and m.get("is_pinned"))
            facts = sum(1 for f in self._facts
                        if f["agent_id"] == agent_id and f.get("valid_to") is None)
            covered = sum((m.get("msg_count") or 0) for m in self._memories
                          if m["agent_id"] == agent_id and m["channel"] == channel
                          and m["level"] == 1)
            return {
                "total_messages": total,
                "l1": _cnt(1), "l2": _cnt(2), "l3": _cnt(3),
                "pinned": pinned, "facts_active": facts,
                "messages_summarized": covered,
            }

    # ── internal ───────────────────────────────────────────────────────
    def _new_channel(self, channel: str) -> dict:
        return {
            "channel": channel, "participants": [], "status": "idle",
            "max_turns": 0, "current_turn": 0, "created_at": _now_iso(),
        }

    def set_channel_participants(self, channel: str, agent_ids: list[str]) -> None:
        """Convenience for the facade — set who's in a channel (already hydrated)."""
        with self._lock:
            ch = self._channels.setdefault(channel, self._new_channel(channel))
            ch["participants"] = list(agent_ids)

    @staticmethod
    def _hydrate(row: dict) -> dict:
        """Return a copy with list fields as real lists (already-parsed)."""
        out = dict(row)
        out["related_entities"] = list(row.get("related_entities") or [])
        out["knows"] = list(row.get("knows") or [])
        return out

    def log_event(self, event_type: str, participants: list[str], description: str,
                  impact: str = "") -> int:
        """Convenience to record a tool/event row (used by some kernel paths)."""
        with self._lock:
            self._event_seq += 1
            self._events.append({
                "id": self._event_seq, "event_type": event_type,
                "participants": ",".join(participants), "description": description,
                "impact": impact, "timestamp": _now_iso(),
            })
            return self._event_seq

    # ── observability (tool calls + usage) — mirror SqliteKernelStore ─────
    def record_tool_call(self, *, community: Optional[str] = None,
                         agent_id: Optional[str] = None,
                         agent_type: Optional[str] = None,
                         channel: Optional[str] = None,
                         tool_name: str = "", args_json: Optional[str] = None,
                         result_preview: Optional[str] = None,
                         ok: bool = False, latency_ms: Optional[int] = None,
                         created_at: Optional[str] = None) -> int:
        with self._lock:
            self._toolcall_seq += 1
            self._tool_calls.append({
                "id": self._toolcall_seq, "community": community,
                "agent_id": agent_id, "agent_type": agent_type, "channel": channel,
                "tool_name": tool_name, "args_json": args_json,
                "result_preview": result_preview, "ok": 1 if ok else 0,
                "latency_ms": latency_ms, "created_at": created_at or _now_iso(),
            })
            return self._toolcall_seq

    def recent_tool_calls(self, *, limit: int = 50, agent_id: Optional[str] = None,
                          community: Optional[str] = None) -> list[dict]:
        with self._lock:
            rows = [
                dict(r) for r in self._tool_calls
                if (agent_id is None or r.get("agent_id") == agent_id)
                and (community is None or r.get("community") == community)
            ]
        rows.sort(key=lambda r: r.get("id", 0), reverse=True)
        return rows[: max(1, min(500, int(limit)))]

    def record_usage(self, *, community: Optional[str] = None,
                     agent_id: Optional[str] = None,
                     agent_type: Optional[str] = None,
                     model: Optional[str] = None, backend: Optional[str] = None,
                     input_tokens: int = 0, output_tokens: int = 0,
                     cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                     est_cost: float = 0.0, estimated: bool = False,
                     latency_ms: Optional[int] = None,
                     was_blocked: bool = False,
                     ts: Optional[str] = None) -> int:
        with self._lock:
            self._usage_seq += 1
            self._usage.append({
                "id": self._usage_seq, "ts": ts or _now_iso(),
                "community": community, "agent_id": agent_id,
                "agent_type": agent_type, "model": model, "backend": backend,
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "cache_read_tokens": int(cache_read_tokens or 0),
                "cache_write_tokens": int(cache_write_tokens or 0),
                "est_cost": float(est_cost or 0.0),
                "estimated": 1 if estimated else 0, "latency_ms": latency_ms,
                "was_blocked": 1 if was_blocked else 0,
            })
            seq = self._usage_seq
        # 예산 캐시 무효화 — 다음 가드 체크가 새 spend 를 반영 (특히 blocked 행).
        try:
            from .. import budget as _budget
            _budget.invalidate(community)
        except Exception:
            pass
        return seq

    def _usage_in_range(self, since: Optional[str], until: Optional[str],
                        community: Optional[str]) -> list[dict]:
        s = _parse_iso(since)
        u = _parse_iso(until)
        out = []
        with self._lock:
            rows = list(self._usage)
        for r in rows:
            if community is not None and r.get("community") != community:
                continue
            ts = _parse_iso(r.get("ts"))
            if s and (ts is None or ts < s):
                continue
            if u and (ts is None or ts >= u):
                continue
            out.append(r)
        return out

    def usage_spend(self, *, since: Optional[str] = None, until: Optional[str] = None,
                    community: Optional[str] = None) -> dict:
        rows = self._usage_in_range(since, until, community)
        lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
        return {
            "total_cost": float(sum(r["est_cost"] for r in rows)),
            "input_tokens": int(sum(r["input_tokens"] for r in rows)),
            "output_tokens": int(sum(r["output_tokens"] for r in rows)),
            "cache_read_tokens": int(sum(r["cache_read_tokens"] for r in rows)),
            "cache_write_tokens": int(sum(r["cache_write_tokens"] for r in rows)),
            "call_count": len(rows),
            "estimated_count": int(sum(r["estimated"] for r in rows)),
            "avg_latency_ms": int(sum(lat) / len(lat)) if lat else 0,
        }

    def usage_by_agent(self, *, since: Optional[str] = None, until: Optional[str] = None,
                       community: Optional[str] = None) -> list[dict]:
        rows = self._usage_in_range(since, until, community)
        groups: dict[tuple, dict] = {}
        for r in rows:
            key = (r.get("agent_id"), r.get("agent_type"), r.get("model"),
                   r.get("backend"))
            g = groups.setdefault(key, {
                "agent_id": r.get("agent_id"), "agent_type": r.get("agent_type"),
                "model": r.get("model"), "backend": r.get("backend"),
                "total_cost": 0.0, "call_count": 0, "input_tokens": 0,
                "output_tokens": 0, "estimated_count": 0,
            })
            g["total_cost"] += r["est_cost"]
            g["call_count"] += 1
            g["input_tokens"] += r["input_tokens"]
            g["output_tokens"] += r["output_tokens"]
            g["estimated_count"] += r["estimated"]
        out = list(groups.values())
        out.sort(key=lambda x: (x["total_cost"], x["call_count"]), reverse=True)
        return out
