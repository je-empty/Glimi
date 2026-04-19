"""
Tool Registry — Glimi 에이전트가 호출 가능한 모든 도구의 선언적 정의.

Claude Code Tool 시스템에서 차용한 개념 (SDK 의존 없음, 순수 프롬프트 레벨):
- name: snake_case 영문 이름 (로컬 모델로 스왑 시에도 호환)
- description: 한 줄 설명 (에이전트 프롬프트에 표시)
- params: dict schema — 런타임 검증용
- category: management | query | request
- applies_to: 호출 가능한 에이전트 타입 집합
- destructive: True면 permission hook 대상
- requires_approval: 승인 절차 필요 (persona → mgr 경로 등)
- handler: 등록된 dispatcher 함수 (tools/handlers.py에서 set_handler로 주입)

호출 방식 (에이전트가 응답 끝에):
<tools>
<call id="1" name="create_room">
{"names": ["은하윤", "수민"], "topic": "게임"}
</call>
</tools>

결과 피드백 (다음 턴 user prompt에 주입):
<tool_result id="1" tool="create_room" ok="true">{"channel": "group-은하윤-수민"}</tool_result>
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict[str, dict]  # name → {"type": str, "required": bool, "desc": str}
    category: str  # "management" | "query" | "request"
    applies_to: frozenset[str]  # {"mgr", "creator", "persona"}
    destructive: bool = False
    requires_approval: bool = False
    handler: Optional[Callable] = None  # 런타임에 set_handler로 주입
    examples: list[str] = field(default_factory=list)


# ── 공통 파라미터 타입 ────────────────────────────────
_str = {"type": "str", "required": True}
_str_opt = {"type": "str", "required": False}
_int = {"type": "int", "required": True}
_int_opt = {"type": "int", "required": False}
_names = {"type": "list[str]", "required": True, "desc": "멤버 이름 목록 (닉네임 아닌 본명)"}


# ── 관리 도구 ──────────────────────────────────────────

MGMT: list[ToolSpec] = [
    ToolSpec(
        name="create_room",
        description="멤버들을 모아 새 톡방(그룹채팅) 생성. 2명이면 internal-dm, 3명+면 internal-group, 오너 포함이면 group",
        params={
            "names": _names,
            "topic": {"type": "str", "required": False, "desc": "톡방 주제 (선택)"},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        examples=['{"names": ["은하윤", "수민"], "topic": "게임 토크"}'],
    ),
    ToolSpec(
        name="start_conversation",
        description="특정 멤버들의 자동 대화 시작 (턴 제한). 채널 없으면 생성",
        params={
            "names": _names,
            "situation": {"type": "str", "required": False, "desc": "대화 상황/주제 힌트"},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="stop_conversation",
        description="자동 대화 중단. target=채널명 또는 '전체'",
        params={"target": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="invite_owner",
        description="오너를 internal 채널에 초대 (group으로 전환)",
        params={"target": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="delete_channel",
        description="채널 삭제 (dm-/mgr- 은 보호됨)",
        params={"target": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
        destructive=True,
    ),
    ToolSpec(
        name="rename_channel",
        description="채널 이름 변경",
        params={"target": _str, "value": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="set_topic",
        description="채널 토픽(설명) 설정",
        params={"target": _str, "value": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="purge_messages",
        description="채널의 최근 메시지 N개 삭제",
        params={
            "target": _str,
            "count": {"type": "int", "required": False, "desc": "기본 100"},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        destructive=True,
    ),
    ToolSpec(
        name="recover_channel",
        description="DB 메시지를 디스코드에 재전송 (purge 후 싱크용)",
        params={"target": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="set_emotion",
        description="특정 멤버의 현재 감정 세팅",
        params={
            "name": _str,
            "emotion": _str,
            "intensity": {"type": "int", "required": True, "desc": "1~10"},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="update_profile",
        description="멤버 프로필 필드 수정. field는 top-level (gender, age, mbti, background) 또는 점 표기 (personality.hobby, speech.style 등)",
        params={
            "name": _str,
            "field": _str,
            "value": _str,
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        examples=[
            '{"name": "은하윤", "field": "gender", "value": "여자"}',
            '{"name": "은하윤", "field": "personality.hobby", "value": "게임, 음악"}',
        ],
    ),
    ToolSpec(
        name="update_relationship",
        description="두 멤버 간 관계 필드 수정",
        params={
            "name_a": _str,
            "name_b": _str,
            "field": _str,
            "value": _str,
        },
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="invoke_agent",
        description="특정 멤버에게 강제 내면 지시 주입 (자연스럽게 말하도록)",
        params={
            "name": _str,
            "target": {"type": "str", "required": True, "desc": "발화할 채널"},
            "instruction": {"type": "str", "required": True, "desc": "내면 생각 문구"},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="reset_channel",
        description="채널 DB 메시지 초기화 (디스코드 채널은 유지)",
        params={"target": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
        destructive=True,
        requires_approval=True,
    ),
    ToolSpec(
        name="clear_messages",
        description="대화 DB 삭제. mode='채널'면 target 필요",
        params={
            "mode": {"type": "str", "required": True, "desc": "'채널' | '전체'"},
            "target": _str_opt,
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        destructive=True,
        requires_approval=True,
    ),
    ToolSpec(
        name="reset_agent",
        description="에이전트 상태·메모리 초기화 (프로필은 유지)",
        params={"name": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
        destructive=True,
        requires_approval=True,
    ),
    ToolSpec(
        name="request_dev_task",
        description="봇 재시작 후 Opus가 코드 수정. args에 요청 내용",
        params={"args": {"type": "str", "required": True, "desc": "개발 요청 상세"}},
        category="management",
        applies_to=frozenset({"mgr"}),
        destructive=True,
        requires_approval=True,
    ),
    ToolSpec(
        name="scene_advance",
        description=(
            "씬(scene)의 phase를 다음/지정 단계로 전환. "
            "튜토리얼: scene_id='tutorial', phase='channels_setup'|'complete' 등. "
            "새 씬(birthday, outing 등) 추가 시 동일 도구로 phase 제어."
        ),
        params={
            "scene_id": {"type": "str", "required": True, "desc": "씬 식별자 (예: 'tutorial')"},
            "phase": {"type": "str", "required": True, "desc": "전환할 phase id (예: 'complete')"},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        examples=['{"scene_id":"tutorial","phase":"channels_setup"}'],
    ),
    # 구버전 호환 alias — 내부적으로 scene_advance 로 위임 (프롬프트에서 여전히 참조)
    ToolSpec(
        name="finish_profile_collection",
        description="[deprecated: scene_advance 선호] 튜토리얼 Phase 1 → 2 트리거 (scene_id=tutorial, phase=channels_setup)",
        params={},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="finish_tutorial",
        description="[deprecated: scene_advance 선호] 튜토리얼 최종 완료 (scene_id=tutorial, phase=complete)",
        params={},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    # creator 전용
    ToolSpec(
        name="create_agent_profile",
        description="신규 페르소나 에이전트 프로필 생성 (JSON)",
        params={"args": {"type": "str", "required": True, "desc": "프로필 JSON"}},
        category="management",
        applies_to=frozenset({"creator"}),
    ),
    ToolSpec(
        name="delete_agent_profile",
        description="에이전트 프로필 삭제",
        params={"name": _str},
        category="management",
        applies_to=frozenset({"creator"}),
        destructive=True,
    ),
    ToolSpec(
        name="set_profile_image",
        description="샘플 프로필 이미지를 에이전트에 적용",
        params={"name": _str, "profile_image_filename": _str},
        category="management",
        applies_to=frozenset({"creator"}),
    ),
    # 승인
    ToolSpec(
        name="approve_request",
        description="페르소나가 제출한 request 승인/거부",
        params={
            "request_id": _str,
            "decision": {"type": "str", "required": True, "desc": "'approve' | 'reject'"},
            "reason": _str_opt,
        },
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    # 메모리 관리 (유나/오너)
    ToolSpec(
        name="pin_memory",
        description=(
            "특정 기억을 고정 (항상 프롬프트 주입). 중요한 결정·감정·사실을 놓치지 않게."
            " target_agent에 대해 memory_id로 지정."
        ),
        params={
            "target_agent": {"type": "str", "required": True, "desc": "어느 멤버의 기억인지 (이름)"},
            "memory_id": {"type": "int", "required": True, "desc": "recall_memory로 찾은 id"},
            "pinned": {"type": "int", "required": False, "desc": "1=고정, 0=해제. 기본 1"},
            "reason": {"type": "str", "required": False, "desc": "왜 고정하는지 (로그용)"},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        examples=['{"target_agent":"서아","memory_id":42,"reason":"어머니 수술 얘기"}'],
    ),
]


# ── 조회 도구 ──────────────────────────────────────────

QUERY: list[ToolSpec] = [
    ToolSpec(
        name="list_channels",
        description="DB에 등록된 채널 목록",
        params={},
        category="query",
        applies_to=frozenset({"mgr", "creator", "persona"}),
    ),
    ToolSpec(
        name="list_members",
        description="등록된 멤버(에이전트) 목록",
        params={},
        category="query",
        applies_to=frozenset({"mgr", "creator"}),
    ),
    ToolSpec(
        name="get_logs",
        description=(
            "채널 대화 로그 조회. 시간 범위 지정으로 최근 N분/특정 구간만 뽑을 수 있어 "
            "불필요한 컨텍스트 낭비 방지."
        ),
        params={
            "target": _str,
            "count": {"type": "int", "required": False, "desc": "최근 N건 (기본 20) — since/from/to 없을 때만 적용"},
            "since_minutes": {"type": "int", "required": False, "desc": "지금부터 N분 전까지 전부"},
            "from_time": {"type": "str", "required": False, "desc": "시작 시각 ISO (예: '2026-04-20 17:30:00')"},
            "to_time": {"type": "str", "required": False, "desc": "종료 시각 ISO — from_time 과 함께"},
            "limit": {"type": "int", "required": False, "desc": "최대 반환 수 (시간 범위 조회 시 토큰 보호, 기본 200)"},
        },
        category="query",
        applies_to=frozenset({"mgr", "creator", "persona"}),
        examples=[
            '{"target":"mgr-creator","count":10}',
            '{"target":"mgr-creator","since_minutes":5}',
            '{"target":"dm-수민","from_time":"2026-04-20 17:00","to_time":"2026-04-20 17:30"}',
        ],
    ),
    ToolSpec(
        name="search_messages",
        description="전체 대화에서 키워드 검색",
        params={"args": {"type": "str", "required": True, "desc": "검색 키워드"}},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="get_speaker_history",
        description="특정 멤버의 발화 이력",
        params={"name": _str},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="get_profile",
        description="멤버 프로필 상세",
        params={"name": _str},
        category="query",
        applies_to=frozenset({"mgr", "creator"}),
    ),
    ToolSpec(
        name="get_relationships",
        description="모든 멤버 간 관계",
        params={},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="get_events",
        description="최근 발생 이벤트",
        params={},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    # 디스코드 실시간 조회
    ToolSpec(
        name="discord_get_logs",
        description="디스코드에서 직접 채널 로그 조회 (DB 아님)",
        params={
            "target": _str,
            "count": {"type": "int", "required": False, "desc": "기본 50"},
        },
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="discord_list_channels",
        description="디스코드 guild의 실제 채널 목록",
        params={},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="discord_list_members",
        description="디스코드 guild 멤버 목록",
        params={},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="discord_get_channel_info",
        description="디스코드 채널 상세 (토픽/권한 등)",
        params={"target": _str},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="discord_get_server",
        description="디스코드 서버 메타 정보",
        params={},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="discord_get_pins",
        description="채널의 핀 메시지 목록",
        params={"target": _str},
        category="query",
        applies_to=frozenset({"mgr"}),
    ),
    # 메모리 조회 — persona/mgr 모두 사용 (자기 기억 deep search)
    ToolSpec(
        name="recall_memory",
        description=(
            "자기 기억을 깊이 검색. 평소 주입 범위 밖의 것도 찾음. "
            "entity (누구 얘기) / query (키워드) / time_range_days 중 하나 이상 지정."
        ),
        params={
            "entity": {"type": "str", "required": False, "desc": "사람 이름 (예: '지우')"},
            "query": {"type": "str", "required": False, "desc": "키워드 검색"},
            "time_range_days": {"type": "int", "required": False, "desc": "최근 N일 내"},
            "limit": {"type": "int", "required": False, "desc": "기본 10, 최대 50"},
        },
        category="query",
        applies_to=frozenset({"persona", "mgr", "creator"}),
        examples=[
            '{"entity":"지우","limit":5}',
            '{"query":"생일","time_range_days":60}',
        ],
    ),
]


# ── 요청 도구 (persona → mgr/creator) ─────────────────

REQUEST: list[ToolSpec] = [
    ToolSpec(
        name="request_dm",
        description="유나/하나한테 DM으로 요청·보고 보내기. target은 '윤하나' 또는 '서유나'",
        params={
            "target": {"type": "str", "required": True, "desc": "'윤하나' | '서유나'"},
            "message": {"type": "str", "required": True, "desc": "요청·보고 내용"},
        },
        category="request",
        applies_to=frozenset({"persona", "creator"}),
        requires_approval=True,
    ),
    ToolSpec(
        name="request_room",
        description="유나한테 톡방 만들어달라고 요청",
        params={
            "names": _names,
            "topic": _str_opt,
        },
        category="request",
        applies_to=frozenset({"persona"}),
        requires_approval=True,
    ),
]


# ── 레지스트리 ────────────────────────────────────────

_ALL_TOOLS: list[ToolSpec] = MGMT + QUERY + REQUEST
TOOLS: dict[str, ToolSpec] = {t.name: t for t in _ALL_TOOLS}


def get_tool(name: str) -> Optional[ToolSpec]:
    return TOOLS.get(name)


def tools_for_agent(agent_type: str) -> list[ToolSpec]:
    """특정 에이전트 타입이 쓸 수 있는 도구 리스트"""
    return [t for t in _ALL_TOOLS if agent_type in t.applies_to]


def set_handler(tool_name: str, handler: Callable):
    """런타임 dispatcher가 handler 함수를 주입"""
    if tool_name not in TOOLS:
        raise KeyError(f"Unknown tool: {tool_name}")
    TOOLS[tool_name].handler = handler
