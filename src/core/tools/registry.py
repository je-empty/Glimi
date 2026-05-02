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
        description="특정 멤버의 현재 감정 세팅. 새 감정 라벨이면 emoji 도 같이 제안 권장 (한 번 매핑되면 같은 emoji 가 일관되게 재사용됨).",
        params={
            "name": _str,
            "emotion": _str,
            "intensity": {"type": "int", "required": True, "desc": "1~10"},
            "emoji": {"type": "str", "required": False, "desc": "이 감정을 시각화할 1글자 이모지 (선택). 처음 등장한 감정이면 이게 영구 매핑됨."},
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        examples=[
            '{"name": "지안", "emotion": "안도", "intensity": 6, "emoji": "🫂"}',
            '{"name": "서연", "emotion": "평온", "intensity": 4}',
        ],
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
        description=(
            "두 멤버 간 관계 필드 수정. "
            "허용 field: 'intimacy' (= 'affection') / 'type' / 'dynamics' 만. 다른 필드명 쓰면 거부됨. "
            "value: intimacy 는 0-100 정수 또는 +N/-N 델타. type/dynamics 는 자유 문자열. "
            "🚫 자기 자신 (caller=mgr/creator) 의 호감도/친밀도 직접 수정 금지 — 자연 누적만."
        ),
        params={
            "name_a": _str,
            "name_b": _str,
            "field": _str,
            "value": _str,
        },
        category="management",
        applies_to=frozenset({"mgr"}),
        examples=[
            '{"name_a":"장서윤","name_b":"아스나","field":"intimacy","value":"+10"}',
            '{"name_a":"장서윤","name_b":"아스나","field":"type","value":"친구"}',
        ],
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
        name="revive_persona",
        description=(
            "메타 박살된 페르소나 부활 — self_aware=1 로 set 해서 자각 유지하며 대화 재개. "
            "사용자가 '서윤이 다시 데려와' 같이 명시 요청할 때만 호출. "
            "데이터(대화·메모리·팩트) 는 hard delete 안 됐으니 그대로 살아남."
        ),
        params={"name": _str},
        category="management",
        applies_to=frozenset({"mgr"}),
    ),
    ToolSpec(
        name="request_dev_task",
        description="[deprecated — use request_dev_fix] 봇 재시작 후 Opus가 코드 수정. args에 요청 내용",
        params={"args": {"type": "str", "required": True, "desc": "개발 요청 상세"}},
        category="management",
        applies_to=frozenset({"mgr"}),
        destructive=True,
        requires_approval=True,
    ),
    ToolSpec(
        name="request_dev_fix",
        description=(
            "Dev manager (세나) 큐에 버그/이슈 보고서 적재. 세나이 분석 → "
            "직접 수정 가능하면 Claude Code (Opus) 로 코드 변경 + 자동 commit/push, "
            "판단 모호하면 오너 검토 큐로 에스컬레이션. mgr/creator 가 chat 에서 직접 "
            "디버깅 / reasoning 노출 / 메타 분석하는 회귀를 막기 위한 표준 통로."
        ),
        params={
            "channel": {"type": "str", "required": True, "desc": "이슈가 발생한 채널명 (예: 'dm-서하')"},
            "severity": {"type": "str", "required": True, "desc": "'low' | 'med' | 'high'"},
            "repro": {"type": "str", "required": True, "desc": "재현 방법 / 발생 상황 (자연어)"},
            "expected": {"type": "str", "required": True, "desc": "기대했던 동작"},
            "actual": {"type": "str", "required": True, "desc": "실제 발생한 동작"},
            "notes": {"type": "str", "required": False, "desc": "추가 컨텍스트 (옵션)"},
        },
        category="management",
        applies_to=frozenset({"mgr", "creator"}),
    ),
    ToolSpec(
        name="dev_organize",
        description=(
            "[dev 전용] pending 요청 분석 + 정리해서 admin 검토 대기 (analyzed) 로 전환. "
            "세나 자체는 코드 수정 안 함 — task_brief / files_hint / confidence 작성. "
            "admin 이 /admin/dev-requests 에서 승인하면 Claude Code 가 batch 로 처리."
        ),
        params={
            "request_id": {"type": "int", "required": True, "desc": "처리할 dev_requests row id"},
            "task_brief": {"type": "str", "required": True, "desc": "Claude Code 에 전달할 작업 지시 (3-6줄, 영문)"},
            "sera_summary": {"type": "str", "required": True, "desc": "한 줄 요약 (admin 카드 표시용)"},
            "files_hint": {"type": "list", "required": False, "desc": "수정 가능성 높은 파일 경로 힌트"},
            "analysis_notes": {"type": "str", "required": False, "desc": "추가 분석 메모 (admin 참고)"},
            "confidence": {"type": "str", "required": True, "desc": "'high' (작은·명확한 수정) | 'low' (사람 판단)"},
        },
        category="management",
        applies_to=frozenset({"dev"}),
    ),
    ToolSpec(
        name="dev_escalate",
        description=(
            "[dev 전용] LOW-confidence — 사람(오너) 판단 필요. 정리된 보고서를 "
            "human_review 큐로 적재. 코드 수정 안 함."
        ),
        params={
            "request_id": {"type": "int", "required": True, "desc": "처리할 dev_requests row id"},
            "summary": {"type": "str", "required": True, "desc": "이슈 요약 (1-2 줄)"},
            "decision_points": {"type": "list", "required": True, "desc": "오너가 결정해야 할 포인트들"},
            "suggested_options": {"type": "list", "required": False, "desc": "선택지 제안 (옵션)"},
            "context_files": {"type": "list", "required": False, "desc": "관련 파일 경로 (옵션)"},
            "severity": {"type": "str", "required": False, "desc": "'low' | 'med' | 'high'"},
        },
        category="management",
        applies_to=frozenset({"dev"}),
    ),
    ToolSpec(
        name="dev_clarify",
        description="[dev 전용] 보고서 내용 모호 시 보고자(유나/하나)에게 추가 질문.",
        params={
            "request_id": {"type": "int", "required": True, "desc": "대상 dev_requests row id"},
            "questions": {"type": "list", "required": True, "desc": "질문 목록"},
        },
        category="management",
        applies_to=frozenset({"dev"}),
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
    ToolSpec(
        name="generate_profile_image",
        description=(
            "샘플 카탈로그에 맞는 얼굴이 없을 때만 호출 — Animagine LoRA 로 신규 portrait 직접 생성. "
            "약 6-7분 소요 (백그라운드, 완료 시 자동으로 채널에 이미지 게시 + 에이전트에 적용). "
            "오너에게 사전 안내 후 호출. character_block 은 영어 (LoRA 가 영어로만 학습됨)."
        ),
        params={
            "name": _str,
            "character_block": {
                "type": "str",
                "required": True,
                "desc": (
                    "영어 캐릭터 설명. 형식: "
                    "'korean female with HAIR, OUTFIT, EXPRESSION, BG gradient background'. "
                    "3-5개 짧은 콤마-구분 phrase. quality / glimistyle / style suffix 자동 wrap — "
                    "직접 쓰지 말 것."
                ),
            },
            "version": {
                "type": "str",
                "required": False,
                "desc": "'v3' (default — 신 캐릭) 또는 'v2' (anchor 3 재현)",
            },
        },
        category="management",
        applies_to=frozenset({"creator"}),
        examples=[
            '{"name":"이루다","character_block":"korean female with high ponytail brown hair, freckles, navy track jacket with white stripes, energetic bright smile, sunny yellow gradient background"}'
        ],
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
        name="get_tool_details",
        description="특정 도구의 전체 스키마 (파라미터 설명·예제·안전 플래그). 기본 프롬프트엔 이름·한줄설명만 실려있음 — 상세 필요 시 호출.",
        params={"name": _str},
        category="query",
        applies_to=frozenset({"mgr", "creator", "persona"}),
        examples=['{"name":"create_room"}'],
    ),
    ToolSpec(
        name="query_knowledge",
        description=(
            "프로젝트 개념/현황을 on-demand 조회. 오너가 '씬이 뭐야?', '도전과제 어떻게?', '너 어디까지 알아?' "
            "같은 질문하면 이걸 호출해서 최신 데이터로 답해. topic ∈ {scenes, achievements, my_tools, permissions, faq}."
        ),
        params={"topic": {"type": "str", "required": True, "desc": "조회할 주제 — scenes/achievements/my_tools/permissions/faq"}},
        category="query",
        applies_to=frozenset({"mgr"}),
        examples=[
            '{"topic":"achievements"}',
            '{"topic":"scenes"}',
            '{"topic":"permissions"}',
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
        description="유나/하나한테 DM으로 메시지 보내기. target은 '윤하나' 또는 '서유나'. mgr 이 쓰면 internal-dm-{sender}-{target} 채널에 직접 글 올리고 상대가 이어감.",
        params={
            "target": {"type": "str", "required": True, "desc": "'윤하나' | '서유나'"},
            "message": {"type": "str", "required": True, "desc": "요청·보고 내용"},
        },
        category="request",
        applies_to=frozenset({"persona", "creator", "mgr"}),
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
    ToolSpec(
        name="bring_friend",
        description=(
            "이미 오너와 친한 (intimacy ≥ 70) 상태에서, 자기 다른 친구를 오너에게 소개하고 "
            "싶을 때 호출. 자연스러운 발화 (\"OO이라는 친구 있는데 소개시켜줄까?\") 와 함께 "
            "이 도구를 같은 응답에서 호출. 시스템이 윤하나(creator)에게 위임 → 오너 컨펌 후 "
            "새 페르소나 생성. 새 친구는 너랑 (절친 75) + 오너랑 (초면 30) 시작."
        ),
        params={
            "friend_name":            {"type": "str", "required": True, "desc": "데려올 친구의 이름 (성+이름, 예: '김도훈')"},
            "friend_concept":         {"type": "str", "required": True, "desc": "어떤 친구인지 (3-5줄): 나이/성별/직업/성격/취향 핵심"},
            "relationship_to_self":   {"type": "str", "required": True, "desc": "데려오는 사람(나) 와의 관계 (예: '대학 동기 절친', '회사 입사동기', '어릴 적부터 친구')"},
            "relationship_dynamics":  {"type": "str", "required": False, "desc": "관계 묘사 1줄 (예: '4년 같은 학교, 매주 술 한 잔')"},
        },
        category="request",
        applies_to=frozenset({"persona"}),
        requires_approval=True,
        examples=[
            '{"friend_name":"김도훈","friend_concept":"28세 남자, 인디게임 개발자, ENTP, 내성적이지만 농담 많음","relationship_to_self":"대학 동기 절친","relationship_dynamics":"4년 같은 컴퓨터공학과, 졸업 후도 매주 연락"}',
        ],
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
