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

    # ── runtime — higher-level (replace raw SQL previously inlined in runtime) ──
    @abstractmethod
    def get_recent_events(self, agent_id: str, event_types: list[str],
                          window_sec: int, limit: int = 8) -> list[dict]:
        """이 에이전트가 최근 window_sec 초 내 트리거한 이벤트 (도구 호출 이력 등)."""
        ...

    @abstractmethod
    def get_agent_channels(self, agent_id: str, exclude_channel: str,
                           include_mgr: bool) -> list[dict]:
        """에이전트가 발화한 채널 + 각 채널 최신 msg id. ``[{channel, last_id}]``.
        include_mgr=False 면 mgr* 채널 제외 (persona 격리)."""
        ...

    @abstractmethod
    def get_memory_coverage(self, agent_id: str, exclude_channel: str) -> dict[str, int]:
        """채널별로 메모리 요약이 커버한 마지막 msg id. ``{channel: last_covered}``."""
        ...

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

    # ── memory — higher-level (replace raw SQL previously inlined in memory) ──
    @abstractmethod
    def set_relationship_dynamics(self, agent_a: str, agent_b: str, dynamics: str) -> None:
        """relationships 행의 dynamics(관계 성격) 텍스트 갱신 + updated_at 터치."""
        ...

    @abstractmethod
    def get_agent_emotion(self, agent_id: str) -> Optional[tuple[str, int]]:
        """에이전트의 현재 감정 ``(emotion, intensity)``. 행 없으면 None.
        intensity 가 NULL 이면 5 로 보정."""
        ...

    @abstractmethod
    def set_agent_emotion(self, agent_id: str, emotion: str, intensity: int) -> None:
        """에이전트의 current_emotion / emotion_intensity 갱신."""
        ...

    @abstractmethod
    def get_uncovered_memories(self, agent_id: str, channel: str, source_level: int) -> list[dict]:
        """롤업 대상 — source_level 메모리 중 상위 레벨(source_level+1)이 아직 커버 못한 것.

        source_level=1 (L2 롤업): level=1 중 msg_id_to > MAX(level=2 의 msg_id_to),
        msg_id_to ASC 정렬. source_level=2 (L3 롤업): level=2 중 id > MAX(level=3 의 id),
        id ASC 정렬. 전부 hydrated dict 로 반환 (BATCH_SIZE 절단/길이 판정은 호출자 몫)."""
        ...

    @abstractmethod
    def get_memories_across_channels(self, agent_id: str, exclude_channel: str,
                                     levels: list[int], limit: int) -> list[dict]:
        """현재 채널 제외, 주어진 level 들의 메모리를 created_at DESC 로 최대 limit 개.
        cross-channel 회상 후보. hydrated dict 반환."""
        ...

    @abstractmethod
    def get_recent_messages_across_channels(self, agent_id: str, exclude_channel: str,
                                            within_minutes: int, limit: int) -> list[dict]:
        """이 에이전트가 최근 within_minutes 분 내 다른 채널에서 한 raw 발화.
        ``[{channel, message, timestamp}]`` (timestamp DESC, 최대 limit)."""
        ...

    @abstractmethod
    def search_memories(self, agent_id: str, entity: Optional[str] = None,
                        query: Optional[str] = None, time_range_days: Optional[int] = None,
                        limit: int = 20) -> list[dict]:
        """deep search — entity(related_entities LIKE) / query(content·mem_type LIKE) /
        time_range_days(최근 N일) 조합. importance DESC, created_at DESC. hydrated dict 반환."""
        ...

    @abstractmethod
    def get_memory(self, memory_id: int) -> Optional[dict]:
        """memories 단건 조회 (hydrated). 없으면 None."""
        ...

    @abstractmethod
    def get_memory_stats(self, agent_id: str, channel: str) -> dict:
        """채널/에이전트 메모리 통계 — ``{total_messages, l1, l2, l3, pinned,
        facts_active, messages_summarized}`` (집계 카운트 묶음)."""
        ...
