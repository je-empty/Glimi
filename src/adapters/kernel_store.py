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


# Convenience singletons for the app to inject at the edge.
kernel_store = SqliteKernelStore()
owner_context = ProfileOwnerContext()
