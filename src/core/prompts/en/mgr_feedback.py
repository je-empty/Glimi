"""mgr/creator 측 inline 프롬프트 모음.

src/bot/mgr_system.py 에서 분리됨 (Phase 2-B pure move — 로직 변경 없음).
빌더 목록:
  - persona_first_greeting_prompt: 새 persona 의 dm 채널 첫 인사
  - conversation_report_prompt:    자율 대화 종료 후 유나 오너 보고
  - room_request_notify_prompt:    에이전트의 톡방 요청 감지 알림
  - action_notify_dm_prompt:       ACTION DM 승인 요청
  - action_notify_room_prompt:     ACTION 톡방 승인 요청
  - action_notify_generic_prompt:  기타 ACTION 승인 요청
"""
from __future__ import annotations


def conversation_report_prompt(
    names: list[str],
    channel: str,
    turn_count: int,
    preview: str,
    oc: str,
) -> str:
    """자율 대화 종료 후 유나가 오너에게 보고 + 후속 판단.

    Args:
        names: 대화 참여 에이전트 이름 리스트
        channel: 대화 채널명
        turn_count: 턴 수
        preview: 마지막 메시지 미리보기
        oc: 오너 호칭

    Returns:
        유나에게 전달할 보고 프롬프트.
    """
    return (
        f"{', '.join(names)} 대화 끝났어 (#{channel}, {turn_count}턴).\n"
        f"마지막 대화:\n{preview}\n\n"
        f"{oc}한테 간략하게 보고해.\n"
        f"대화 내용에서 누군가가 {oc}한테 연락하겠다고 했거나 다른 사람한테 연락하려는 상황이면 "
        f"`start_conversation` 도구로 이어지게 해줘.\n"
        f"에이전트에게 강제 지시(임의 발화 주입)는 절대 금지."
    )


def room_request_notify_prompt(agent_name: str, message: str) -> str:
    """에이전트가 톡방 요청한 걸 유나에게 알림.

    Args:
        agent_name: 요청한 에이전트 이름
        message: 요청 메시지 snippet
    """
    return (
        f"{agent_name}이(가) 톡방/그룹채팅을 원하는 것 같아. "
        f"메시지: \"{message[:60]}\"\n"
        f"필요하면 `create_room` 도구로 만들어줘."
    )


def _action_judge_guide(oc: str) -> str:
    return (
        "판단 기준:\n"
        f"- 자연스러운 요청이면 승인하고 {oc}한테 간략 보고 (예: '서연이가 소율이한테 DM 보내려고 해서 승인했어')\n"
        f"- 이상하거나 판단 어려우면 거절하지 말고 {oc}한테 먼저 물어봐 (예: '{oc} 이거 승인할까?')"
    )


def action_notify_dm_prompt(
    agent_name: str,
    agent_id: str,
    target_name: str,
    dm_message: str,
    oc: str,
) -> str:
    """페르소나의 DM 요청 알림 (유나에게). DM 은 자동 실행되므로 알림·상황 공유용."""
    return (
        f"[요청 알림]\n"
        f"{agent_name}이(가) {target_name}한테 DM 보냈어:\n"
        f"  \"{dm_message[:100]}\"\n\n"
        f"{_action_judge_guide(oc)}"
    )


def action_notify_room_prompt(
    agent_name: str,
    agent_id: str,
    room_info: str,
    first_msg: str,
    oc: str,
) -> str:
    """페르소나의 톡방 요청 알림 (유나에게). 판단 후 `create_room` 도구로 생성."""
    return (
        f"[요청 알림]\n"
        f"{agent_name}이(가) 톡방 만들고 싶대:\n"
        f"  참여자: {room_info}\n"
        f"  첫 메시지: \"{first_msg[:100]}\"\n\n"
        f"승인한다면 `create_room` 도구로 만들어 (name/participants/first_message 인자).\n"
        f"{_action_judge_guide(oc)}"
    )


def action_notify_generic_prompt(
    agent_name: str,
    action_str: str,
    oc: str,
) -> str:
    """기타 행동 요청 알림 (유나에게)."""
    return (
        f"[요청 알림]\n"
        f"{agent_name}이(가) 행동을 요청했어:\n"
        f"  → {action_str}\n\n"
        f"승인하려면 상황에 맞는 도구를 호출해.\n"
        f"{_action_judge_guide(oc)}"
    )


def persona_first_greeting_prompt(
    dm_name: str,
    call: str,
) -> str:
    """새로 만든 persona 에이전트가 자기 dm 채널에서 오너에게 첫 인사.

    Args:
        dm_name: 채널 이름 (예: 'dm-한소율')
        call: 오너 호칭 (별명 > 이름 순)

    Returns:
        persona 에이전트에게 전달할 첫 인사 프롬프트.
    """
    return (
        f"[상황] 이 채널(#{dm_name})은 너랑 {call} 둘만의 공간. "
        f"{call}이 방금 들어와서 너랑 처음 대화 시작하는 순간.\n"
        f"[지시] {call}에게 자연스럽게 첫 인사. "
        f"네 성격·배경 살리면서 2~4 짧은 메시지로. "
        f"자기소개 간단히 + 가벼운 한마디 (질문이나 안부).\n"
        f"[중요] 메타 발언 금지. 다음 표현 쓰지 마:\n"
        f"  - '방금 만들어졌다' / '누가 나를 만들었다' / '디자인됐다'\n"
        f"  - '하나' / '윤하나' / '유나' / '서유나' / 'Creator' / 'mgr' 이름 언급\n"
        f"  - '에이전트' / '봇' / '캐릭터' / 'AI' / '시스템' / '여기 뭐 하는 곳'\n"
        f"너는 그냥 평범한 사람이고, 처음 보는 {call} 한테 말 거는 거.\n"
        f"[스타일] 카톡처럼. 네 말투로. 로봇 같은 정형화된 인사 금지.\n"
        f"[금지] <tools> 블록 쓰지 마. 지금은 chat 인사만."
    )
