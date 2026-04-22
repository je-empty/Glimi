"""mgr/creator 측 inline 프롬프트 모음.

src/bot/mgr_system.py 에서 분리됨 (Phase 2-B pure move — 로직 변경 없음).
현재 이관 완료:
  - persona_first_greeting_prompt: 새 persona 에이전트의 dm 채널 첫 인사

TODO (Phase 2-B 남은 범위):
  - report_prompt (대화 종료 후 유나 보고)
  - room_request notify_prompt (톡방 요청 감지)
  - action_notify_prompt (ACTION 승인 요청, DM/톡방/기타 3 variant)
"""
from __future__ import annotations


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
