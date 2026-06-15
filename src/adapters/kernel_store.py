"""SQLite-backed implementation of the kernel's :class:`KernelStore` interface,
plus the owner-context adapter.

This is the single place where the kernel's storage needs are mapped onto the
Hangout app's ``src.db`` module. The kernel modules (once migrated) call
``store.<method>`` instead of ``db.<fn>`` / raw SQL — so all SQL lives here.
"""
from __future__ import annotations

from typing import Optional

from src import db
from src.core import profile
from src.glimi.store import KernelStore


class SqliteKernelStore(KernelStore):
    """:class:`KernelStore` over the app's ``src.db`` (SQLite)."""

    # ── conversation engine ───────────────────────────────────────────
    def set_channel_status(self, channel: str, status: str, max_turns: int = 0) -> None:
        db.set_channel_status(channel, status, max_turns)

    def increment_channel_turn(self, channel: str) -> int:
        return db.increment_channel_turn(channel)

    def get_recent_messages(self, channel: str, limit: int = 20) -> list[dict]:
        return db.get_recent_messages(channel, limit)

    def get_messages_by_range(self, channel: str, after_id: int, limit: int = 15) -> list[dict]:
        return db.get_messages_by_range(channel, after_id, limit)

    # ── runtime ───────────────────────────────────────────────────────
    def get_agent(self, agent_id: str) -> Optional[dict]:
        return db.get_agent(agent_id)

    def list_agents(self, agent_type: Optional[str] = None) -> list[dict]:
        return db.list_agents(agent_type)

    def get_channel_participants(self, channel: str) -> list[str]:
        return db.get_channel_participants(channel)

    def get_channel_overview(self) -> list[dict]:
        return db.get_channel_overview()

    def get_agent_model_override(self, agent_id: str) -> Optional[str]:
        return db.get_agent_model_override(agent_id)

    def log_message(self, channel: str, speaker: str, message: str, emotion: Optional[str] = None) -> None:
        db.log_message(channel, speaker, message, emotion)

    def add_message_hook(self, fn) -> None:
        db.add_message_hook(fn)

    # ── runtime — higher-level (raw SQL lives here, not in the kernel) ──
    def get_recent_events(self, agent_id: str, event_types: list[str],
                          window_sec: int, limit: int = 8) -> list[dict]:
        if not event_types:
            return []
        conn = db.get_conn()
        try:
            placeholders = ",".join("?" for _ in event_types)
            rows = conn.execute(
                f"SELECT event_type, participants, description, timestamp FROM events "
                f"WHERE timestamp >= datetime('now', ?) "
                f"AND event_type IN ({placeholders}) "
                f"AND participants LIKE ? "
                f"ORDER BY id DESC LIMIT ?",
                (f"-{window_sec} seconds", *event_types, f"{agent_id},%", limit),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def get_agent_channels(self, agent_id: str, exclude_channel: str,
                           include_mgr: bool) -> list[dict]:
        conn = db.get_conn()
        try:
            if include_mgr:
                rows = conn.execute(
                    """SELECT channel, MAX(id) as last_id FROM conversations
                       WHERE speaker = ? AND channel != ?
                       GROUP BY channel ORDER BY last_id DESC""",
                    (agent_id, exclude_channel),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT channel, MAX(id) as last_id FROM conversations
                       WHERE speaker = ? AND channel != ? AND channel NOT LIKE 'mgr%'
                       GROUP BY channel ORDER BY last_id DESC""",
                    (agent_id, exclude_channel),
                ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def get_memory_coverage(self, agent_id: str, exclude_channel: str) -> dict[str, int]:
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT channel, MAX(msg_id_to) as last_covered FROM memories "
                "WHERE agent_id = ? AND channel != ? GROUP BY channel",
                (agent_id, exclude_channel),
            ).fetchall()
        finally:
            conn.close()
        return {r["channel"]: (r["last_covered"] or 0) for r in rows}

    # ── memory ────────────────────────────────────────────────────────
    def get_agent_by_name(self, name: str) -> Optional[dict]:
        return db.get_agent_by_name(name)

    def get_relationship(self, agent_a: str, agent_b: str) -> Optional[dict]:
        return db.get_relationship(agent_a, agent_b)

    def get_relationship_history(self, agent_a: str, agent_b: str, limit: int = 20) -> list[dict]:
        return db.get_relationship_history(agent_a, agent_b, limit)

    def update_intimacy(self, agent_a: str, agent_b: str, delta: int) -> None:
        db.update_intimacy(agent_a, agent_b, delta)

    def add_relationship_delta(self, agent_a: str, agent_b: str, delta_type: str,
                               from_state: Optional[str] = None, to_state: Optional[str] = None,
                               reason: Optional[str] = None, source_channel: Optional[str] = None,
                               source_memory_id: Optional[int] = None) -> int:
        return db.add_relationship_delta(
            agent_a, agent_b, delta_type, from_state=from_state, to_state=to_state,
            reason=reason, source_channel=source_channel, source_memory_id=source_memory_id,
        )

    def get_memories(self, agent_id: str, channel: str, level: int, limit: int = 10) -> list[dict]:
        return db.get_memories(agent_id, channel, level, limit)

    def get_latest_memory(self, agent_id: str, channel: str, level: int) -> Optional[dict]:
        return db.get_latest_memory(agent_id, channel, level)

    def get_pinned_memories(self, agent_id: str, limit: int = 20) -> list[dict]:
        return db.get_pinned_memories(agent_id, limit)

    def add_memory(self, agent_id: str, channel: str, level: int, content: str,
                   msg_id_from: Optional[int] = None, msg_id_to: Optional[int] = None,
                   msg_count: int = 0, mem_type: Optional[str] = None,
                   related_entities: Optional[list] = None, knows: Optional[list] = None,
                   importance: int = 5, is_pinned: bool = False,
                   parent_memory_id: Optional[int] = None,
                   related_agent_id: Optional[str] = None) -> int:
        return db.add_memory(
            agent_id, channel, level, content,
            msg_id_from=msg_id_from, msg_id_to=msg_id_to, msg_count=msg_count,
            mem_type=mem_type, related_entities=related_entities, knows=knows,
            importance=importance, is_pinned=is_pinned,
            parent_memory_id=parent_memory_id, related_agent_id=related_agent_id,
        )

    def set_pin(self, memory_id: int, pinned: bool = True) -> None:
        db.set_pin(memory_id, pinned)

    def touch_memory_access(self, memory_ids: list[int]) -> None:
        db.touch_memory_access(memory_ids)

    def count_messages_after(self, channel: str, after_id: int) -> int:
        return db.count_messages_after(channel, after_id)

    def get_facts(self, agent_id: str, subject: Optional[str] = None,
                  include_invalid: bool = False, limit: int = 50) -> list[dict]:
        return db.get_facts(agent_id, subject=subject, include_invalid=include_invalid, limit=limit)

    def add_fact(self, agent_id: str, subject: str, predicate: str, object_value: str,
                 source_channel: Optional[str] = None, source_memory_id: Optional[int] = None,
                 confidence: float = 1.0, importance: int = 5) -> int:
        return db.add_fact(
            agent_id, subject, predicate, object_value,
            source_channel=source_channel, source_memory_id=source_memory_id,
            confidence=confidence, importance=importance,
        )

    def list_users(self) -> list[dict]:
        return db.list_users()

    # ── memory — higher-level (raw SQL lives here, not in the kernel) ──
    def set_relationship_dynamics(self, agent_a: str, agent_b: str, dynamics: str) -> None:
        from src.core.timeutil import now_utc_iso
        conn = db.get_conn()
        try:
            conn.execute(
                "UPDATE relationships SET dynamics=?, updated_at=? WHERE agent_a=? AND agent_b=?",
                (dynamics, now_utc_iso(), agent_a, agent_b),
            )
            conn.commit()
        finally:
            conn.close()

    def get_agent_emotion(self, agent_id: str) -> Optional[tuple[str, int]]:
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT current_emotion, emotion_intensity FROM agents WHERE id=?",
                (agent_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return (row["current_emotion"], row["emotion_intensity"] or 5)

    def set_agent_emotion(self, agent_id: str, emotion: str, intensity: int) -> None:
        conn = db.get_conn()
        try:
            conn.execute(
                "UPDATE agents SET current_emotion=?, emotion_intensity=? WHERE id=?",
                (emotion, intensity, agent_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_uncovered_memories(self, agent_id: str, channel: str, source_level: int) -> list[dict]:
        target_level = source_level + 1
        conn = db.get_conn()
        try:
            if source_level == 1:
                # L2 롤업 — 커버 커서는 level=2 의 MAX(msg_id_to), 필터/정렬은 msg_id_to
                latest = conn.execute(
                    "SELECT MAX(msg_id_to) as last_id FROM memories "
                    "WHERE agent_id=? AND channel=? AND level=?",
                    (agent_id, channel, target_level),
                ).fetchone()
                last_covered = latest["last_id"] if latest and latest["last_id"] else 0
                rows = conn.execute(
                    """SELECT * FROM memories
                       WHERE agent_id=? AND channel=? AND level=? AND msg_id_to > ?
                       ORDER BY msg_id_to ASC""",
                    (agent_id, channel, source_level, last_covered),
                ).fetchall()
            else:
                # L3 롤업 — 커버 커서는 level=3 의 MAX(id), 필터/정렬은 id
                latest = conn.execute(
                    "SELECT MAX(id) as last_id FROM memories "
                    "WHERE agent_id=? AND channel=? AND level=?",
                    (agent_id, channel, target_level),
                ).fetchone()
                last_covered = latest["last_id"] if latest and latest["last_id"] else 0
                rows = conn.execute(
                    """SELECT * FROM memories
                       WHERE agent_id=? AND channel=? AND level=? AND id > ?
                       ORDER BY id ASC""",
                    (agent_id, channel, source_level, last_covered),
                ).fetchall()
        finally:
            conn.close()
        return [db._hydrate_memory(r) for r in rows]

    def get_memories_across_channels(self, agent_id: str, exclude_channel: str,
                                     levels: list[int], limit: int) -> list[dict]:
        if not levels:
            return []
        conn = db.get_conn()
        try:
            placeholders = ",".join("?" for _ in levels)
            rows = conn.execute(
                f"""SELECT * FROM memories
                    WHERE agent_id=? AND channel != ? AND level IN ({placeholders})
                    ORDER BY created_at DESC LIMIT ?""",
                (agent_id, exclude_channel, *levels, limit),
            ).fetchall()
        finally:
            conn.close()
        return [db._hydrate_memory(r) for r in rows]

    def get_recent_messages_across_channels(self, agent_id: str, exclude_channel: str,
                                            within_minutes: int, limit: int) -> list[dict]:
        conn = db.get_conn()
        try:
            rows = conn.execute(
                "SELECT channel, message, timestamp FROM conversations "
                "WHERE speaker=? AND channel != ? "
                "  AND timestamp >= datetime('now', ?) "
                "ORDER BY timestamp DESC LIMIT ?",
                (agent_id, exclude_channel, f"-{int(within_minutes)} minutes", limit),
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def search_memories(self, agent_id: str, entity: Optional[str] = None,
                        query: Optional[str] = None, time_range_days: Optional[int] = None,
                        limit: int = 20) -> list[dict]:
        sql = "SELECT * FROM memories WHERE agent_id=?"
        args: list = [agent_id]
        if entity:
            sql += " AND related_entities LIKE ?"
            args.append(f'%"{entity}"%')
        if query:
            sql += " AND (content LIKE ? OR mem_type LIKE ?)"
            args.append(f"%{query}%")
            args.append(f"%{query}%")
        if time_range_days:
            sql += " AND created_at >= datetime('now', ?)"
            args.append(f"-{int(time_range_days)} days")
        sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
        args.append(max(1, min(50, int(limit))))
        conn = db.get_conn()
        try:
            rows = conn.execute(sql, args).fetchall()
        finally:
            conn.close()
        return [db._hydrate_memory(r) for r in rows]

    def get_memory(self, memory_id: int) -> Optional[dict]:
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
        finally:
            conn.close()
        return db._hydrate_memory(row) if row else None

    def get_memory_stats(self, agent_id: str, channel: str) -> dict:
        conn = db.get_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) as c FROM conversations WHERE channel=?",
                (channel,),
            ).fetchone()["c"]

            def _cnt(level):
                return conn.execute(
                    "SELECT COUNT(*) as c FROM memories WHERE agent_id=? AND channel=? AND level=?",
                    (agent_id, channel, level),
                ).fetchone()["c"]

            l1 = _cnt(1)
            l2 = _cnt(2)
            l3 = _cnt(3)
            pinned = conn.execute(
                "SELECT COUNT(*) as c FROM memories WHERE agent_id=? AND is_pinned=1",
                (agent_id,),
            ).fetchone()["c"]
            facts = conn.execute(
                "SELECT COUNT(*) as c FROM agent_facts WHERE agent_id=? AND valid_to IS NULL",
                (agent_id,),
            ).fetchone()["c"]
            covered = conn.execute(
                "SELECT COALESCE(SUM(msg_count),0) as t FROM memories "
                "WHERE agent_id=? AND channel=? AND level=1",
                (agent_id, channel),
            ).fetchone()["t"]
        finally:
            conn.close()
        return {
            "total_messages": total,
            "l1": l1,
            "l2": l2,
            "l3": l3,
            "pinned": pinned,
            "facts_active": facts,
            "messages_summarized": covered,
        }


class ProfileOwnerContext:
    """:class:`~src.glimi.profiles.OwnerContext` over ``src.core.profile``."""

    def name(self) -> str:
        return profile.get_user_name()

    def id(self) -> str:
        return profile.get_user_id()

    def display_name(self) -> str:
        return profile.get_user_display_name()

    def call_name(self) -> str:
        return profile.get_owner_call_name()

    def profile(self) -> dict:
        return profile.get_user_profile() or {}


class ProfileProviderAdapter:
    """:class:`~src.glimi.profiles.ProfileProvider` over ``src.core.profile`` +
    the app's prompt builder (``build_system_prompt``)."""

    def get(self, agent_id: str):
        return profile.load_profile(agent_id)

    def system_prompt(self, agent_id: str, include_profile_image_template: bool = False) -> str:
        return profile.build_system_prompt(agent_id, include_profile_image_template=include_profile_image_template)

    def display_name(self, agent_id: str) -> str:
        return profile.get_agent_display_name(agent_id)


class LogWriterObserver:
    """:class:`~src.glimi.observability.KernelObserver` over ``src.log_writer``
    (the app's live dashboard / log sink)."""

    def system(self, message: str) -> None:
        from src import log_writer
        log_writer.system(message)

    def agent_thinking(self, agent_id: str, line: str) -> None:
        from src import log_writer
        log_writer.agent_thinking(agent_id, line)

    def chat(self, channel: str, speaker: str, message: str) -> None:
        from src import log_writer
        log_writer.chat(channel, speaker, message)

    def mark_thinking(self, agent_id: str, channel: str = "") -> None:
        from src import log_writer
        log_writer.mark_thinking(agent_id, channel)

    def mark_done(self, agent_id: str) -> None:
        from src import log_writer
        log_writer.mark_done(agent_id)

    def is_thinking(self, agent_id: str) -> bool:
        from src import log_writer
        return log_writer.is_thinking(agent_id)


# Convenience singletons for the app to inject at the edge.
kernel_store = SqliteKernelStore()
owner_context = ProfileOwnerContext()
profile_provider = ProfileProviderAdapter()
observer = LogWriterObserver()
