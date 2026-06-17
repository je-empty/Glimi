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
    def log_message(self, channel: str, speaker: str, message: str,
                    emotion: Optional[str] = None,
                    reply_to: Optional[int] = None) -> Optional[int]:
        """메시지를 기록하고 **생성된 row id 를 반환**.

        반환값을 무시하는 기존 호출부도 그대로 동작 (backward-compatible).
        ``reply_to`` 가 주어지면 부모 메시지의 ``thread_root`` (없으면 부모 id) 를
        이 메시지의 thread_root 로 denormalize. 30 초 turn-dedupe 에 걸리면 새 행을
        만들지 않고 **기존 행의 id** 를 반환 (None 이 아님)."""
        ...

    @abstractmethod
    def add_message_hook(self, fn) -> None:
        """log_message 직후 호출될 콜백 등록. 시그니처: ``fn(channel, speaker, message)``.
        커널(memory)이 오너 메시지 트리거를 받는 옵저버 경로."""
        ...

    # ── reactions / replies / threads ─────────────────────────────────
    @abstractmethod
    def add_reaction(self, message_id: int, actor_id: str, emoji: str) -> bool:
        """메시지에 리액션 추가. UNIQUE(message_id, actor_id, emoji) 로 멱등.

        새로 추가됐으면 True, 이미 있어 무시됐으면 (또는 부모 메시지 부재로
        FK 위반) False. 호출자는 True 일 때만 관계 신호 등 side-effect 적용."""
        ...

    @abstractmethod
    def remove_reaction(self, message_id: int, actor_id: str, emoji: str) -> None:
        """리액션 제거 (toggle-off). 없으면 no-op."""
        ...

    @abstractmethod
    def get_reactions(self, message_id: int) -> list[dict]:
        """단일 메시지의 리액션 목록. ``[{emoji, actor_id, created_at}]`` (created_at ASC)."""
        ...

    @abstractmethod
    def get_reactions_for(self, message_ids: list[int]) -> dict[int, list[dict]]:
        """여러 메시지의 리액션을 한 번에. ``{message_id: [{emoji, actor_id, created_at}]}``.
        리액션 없는 메시지는 키 자체가 없음. N+1 방지용 배치 조회."""
        ...

    @abstractmethod
    def set_reply(self, message_id: int, reply_to: int) -> None:
        """기존 메시지를 답글로 표시 — reply_to + thread_root (부모의 thread_root or 부모 id) 설정."""
        ...

    @abstractmethod
    def get_thread(self, root_id: int, limit: int = 50) -> list[dict]:
        """스레드 전체 (루트 + 모든 답글), id ASC. ``WHERE thread_root=? OR id=?``.
        hydrated dict 리스트 (없으면 빈 리스트)."""
        ...

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

    # ── observability — tool calls + LLM usage (concrete, not abstract) ──
    # 이 두 묶음은 **추상이 아니라 구체 no-op/빈 기본값** 으로 둔다. 이유:
    #   - 신규 추상 메서드를 추가하면 InMemoryKernelStore + 테스트 더블이 전부 깨진다
    #     (기존 테스트 green 유지가 최우선). 관측은 부가 기능 — 없는 store 는 그냥 안 적고
    #     빈 결과를 돌려주면 된다 (DashboardReader 의 never-raise 계약과도 맞음).
    #   - 영속화하는 store (SqliteKernelStore) 는 아래를 override 한다.
    #   - 인메모리 store 도 필요하면 override 가능 (harness 레벨 테스트용).

    def record_tool_call(self, *, community: Optional[str] = None,
                         agent_id: Optional[str] = None,
                         agent_type: Optional[str] = None,
                         channel: Optional[str] = None,
                         tool_name: str = "", args_json: Optional[str] = None,
                         result_preview: Optional[str] = None,
                         ok: bool = False, latency_ms: Optional[int] = None,
                         created_at: Optional[str] = None) -> int:
        """도구 호출 1건 기록. 기본 구현 = no-op (관측 미지원 store). 영속 store 는 override.
        반환 = 생성된 row id (no-op 은 0)."""
        return 0

    def recent_tool_calls(self, *, limit: int = 50, agent_id: Optional[str] = None,
                          community: Optional[str] = None) -> list[dict]:
        """최근 도구 호출 목록 (최신 우선). 기본 구현 = 빈 리스트. 영속 store 는 override.
        각 dict: ``{id, community, agent_id, agent_type, channel, tool_name,
        args_json, result_preview, ok, latency_ms, created_at}``."""
        return []

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
        """한 번의 LLM 호출 사용량/비용 1행 기록. 기본 구현 = no-op. 영속 store 는 override.
        ``estimated`` = True 면 토큰이 추정치 (CLI 경로). ``was_blocked`` = True 면 예산
        가드가 Claude 호출을 막은 행 (backend='capped', est_cost=0). 반환 = row id (no-op 은 0)."""
        return 0

    def usage_spend(self, *, since: Optional[str] = None, until: Optional[str] = None,
                    community: Optional[str] = None) -> dict:
        """기간 사용량 집계. 기본 구현 = 0 채운 dict. 영속 store 는 override.
        ``{total_cost, input_tokens, output_tokens, cache_read_tokens,
        cache_write_tokens, call_count, estimated_count, avg_latency_ms}``."""
        return {
            "total_cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "call_count": 0,
            "estimated_count": 0,
            "avg_latency_ms": 0,
        }

    def usage_by_agent(self, *, since: Optional[str] = None, until: Optional[str] = None,
                       community: Optional[str] = None) -> list[dict]:
        """agent_id 별 사용량 GROUP BY. 기본 구현 = 빈 리스트. 영속 store 는 override."""
        return []
