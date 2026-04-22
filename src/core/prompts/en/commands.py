"""수동 디스코드 명령 (src/bot/commands.py) 에서 쓰는 프롬프트.

src/bot/commands.py 에서 분리됨 (Phase 2-B pure move — 로직 변경 없음).
빌더 목록:
  - create_agent_prompt:  !캐릭터생성 에서 하나한테 JSON 프로필 요청
  - profile_image_prompt: 프로필 이미지 생성용 외부 LLM 프롬프트 (ChatGPT/Gemini 복붙용)
  - analyze_logs_prompt:  !분석 에서 유나한테 최근 대화 분석 요청
"""
from __future__ import annotations


def create_agent_prompt(new_id: str, concept: str) -> str:
    """하나에게 새 persona 에이전트 JSON 프로필 생성 요청."""
    return (
        f"새로운 페르소나 에이전트를 생성해줘.\n"
        f"에이전트 ID: {new_id}\n"
        f"컨셉: {concept}\n\n"
        f"반드시 완전한 JSON 프로필을 출력해. "
        f"기존 에이전트 프로필 구조와 동일하게. "
        f"JSON만 출력하고 다른 텍스트는 넣지 마."
    )


def profile_image_prompt(age, outfit_hint: str, char_detail: str) -> str:
    """프로필 이미지 생성용 외부 LLM (ChatGPT / Gemini) 프롬프트.
    하나가 만든 캐릭터 상세를 그림 생성 지시문으로 감싸서 return.
    """
    base_prompt = (
        f"Anime-style profile illustration, Korean girl, age {age}, "
        f"{outfit_hint}, clean lineart, soft cel shading, "
        f"pastel gradient background, bust-up shot, slightly asymmetrical natural pose, "
        f"subtle catchlight in eyes, consistent art style similar to modern slice-of-life anime "
        f"(like Horimiya or Oregairu visual style)"
    )
    return f"{base_prompt}\n{char_detail}"


def analyze_logs_prompt(log_text: str) -> str:
    """유나한테 최근 대화 로그 분석 요청 (!분석)."""
    return (
        f"최근 대화 로그를 분석해서 보고해줘:\n\n"
        f"{log_text}\n\n"
        f"1. 각 에이전트의 현재 상태/감정 추정\n"
        f"2. 주목할 만한 관계 변화\n"
        f"3. 대화에서 언급된 제3의 인물이 있다면 알려줘\n"
        f"4. 새로운 에이전트를 추가하면 좋을 것 같은지 판단해. 있다면 어떤 캐릭터가 좋을지 제안해\n\n"
        f"네 말투(고1 여자애)로 보고해."
    )
