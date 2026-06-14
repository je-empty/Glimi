"""KernelStore — the data-store interface the Glimi kernel depends on.

The kernel (runtime / memory / conversation) must never import the hosting
app's database layer directly. Instead it talks to this abstract interface, and
the app provides a concrete implementation (see the SQLite adapter in the app
layer). This is the seam that lets Glimi Core stay domain- and storage-neutral.

Status: grows as kernel modules migrate off ``src.db`` (conversation → runtime
→ memory). The 25 methods below are the direct ``db.*`` calls those modules
make. A second tranche of higher-level methods (replacing raw-SQL blocks
currently inlined in runtime/memory — e.g. ``search_memories``,
``get_memory_stats``, ``get_agent_channels``) lands together with those module
migrations so the kernel ends up with *zero* SQL.

All ``dict`` returns are hydrated (JSON columns already parsed); callers never
see raw rows.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class KernelStore(ABC):
    # ── conversation engine ───────────────────────────────────────────
    @abstractmethod
    def set_channel_status(self, channel: str, status: str, max_turns: int = 0) -> None: ...

    @abstractmethod
    def increment_channel_turn(self, channel: str) -> int: ...

    @abstractmethod
    def get_recent_messages(self, channel: str, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    def get_messages_by_range(self, channel: str, after_id: int, limit: int = 15) -> list[dict]: ...

    # ── runtime ───────────────────────────────────────────────────────
    @abstractmethod
    def get_agent(self, agent_id: str) -> Optional[dict]: ...

    @abstractmethod
    def list_agents(self, agent_type: Optional[str] = None) -> list[dict]: ...

    @abstractmethod
    def get_channel_participants(self, channel: str) -> list[str]: ...

    @abstractmethod
    def get_channel_overview(self) -> list[dict]: ...

    @abstractmethod
    def get_agent_model_override(self, agent_id: str) -> Optional[str]: ...

    @abstractmethod
    def log_message(self, channel: str, speaker: str, message: str, emotion: Optional[str] = None) -> None: ...

    # ── memory ────────────────────────────────────────────────────────
    @abstractmethod
    def get_agent_by_name(self, name: str) -> Optional[dict]: ...

    @abstractmethod
    def get_relationship(self, agent_a: str, agent_b: str) -> Optional[dict]: ...

    @abstractmethod
    def get_relationship_history(self, agent_a: str, agent_b: str, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    def update_intimacy(self, agent_a: str, agent_b: str, delta: int) -> None: ...

    @abstractmethod
    def add_relationship_delta(self, agent_a: str, agent_b: str, delta_type: str,
                               from_state: Optional[str] = None, to_state: Optional[str] = None,
                               reason: Optional[str] = None, source_channel: Optional[str] = None,
                               source_memory_id: Optional[int] = None) -> int: ...

    @abstractmethod
    def get_memories(self, agent_id: str, channel: str, level: int, limit: int = 10) -> list[dict]: ...

    @abstractmethod
    def get_latest_memory(self, agent_id: str, channel: str, level: int) -> Optional[dict]: ...

    @abstractmethod
    def get_pinned_memories(self, agent_id: str, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    def add_memory(self, agent_id: str, channel: str, level: int, content: str,
                   msg_id_from: Optional[int] = None, msg_id_to: Optional[int] = None,
                   msg_count: int = 0, mem_type: Optional[str] = None,
                   related_entities: Optional[list] = None, knows: Optional[list] = None,
                   importance: int = 5, is_pinned: bool = False,
                   parent_memory_id: Optional[int] = None,
                   related_agent_id: Optional[str] = None) -> int: ...

    @abstractmethod
    def set_pin(self, memory_id: int, pinned: bool = True) -> None: ...

    @abstractmethod
    def touch_memory_access(self, memory_ids: list[int]) -> None: ...

    @abstractmethod
    def count_messages_after(self, channel: str, after_id: int) -> int: ...

    @abstractmethod
    def get_facts(self, agent_id: str, subject: Optional[str] = None,
                  include_invalid: bool = False, limit: int = 50) -> list[dict]: ...

    @abstractmethod
    def add_fact(self, agent_id: str, subject: str, predicate: str, object_value: str,
                 source_channel: Optional[str] = None, source_memory_id: Optional[int] = None,
                 confidence: float = 1.0, importance: int = 5) -> int: ...

    @abstractmethod
    def list_users(self) -> list[dict]: ...
