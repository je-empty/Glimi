"""Language-specific prompt snippets — culture·linguistic cue centralization.

English prompt modules (`en/*.py`) use these helpers to inject locale-aware fragments so a
single prompt template serves multiple languages. For Korean communities the LLM needs actual
Korean examples (ㅇㅇ / ㅋㅋ / 카톡) to correctly judge conversational context — abstract
English-only examples miss the nuance.

Add new snippet functions here as additional cultural patterns surface during QA.
"""
from __future__ import annotations


def _lang() -> str:
    try:
        from src.community import get_language
        return get_language() or "en"
    except Exception:
        return "en"


# ── Short acknowledgement examples ─────────────────────────────────────────
# Used in mgr/creator rule 11·rule 4 — distinguishes "feedback to already-dispatched request"
# from "new request". LLM must recognize these as NOT a new request.

def simple_ack_examples() -> str:
    if _lang() == "ko":
        return '"ㅇㅇ", "ㅇㅋ", "응", "ㅋㅋ", "고마워", "부탁해", "맡길게", "굿", "오키"'
    return '"ok", "kk", "yeah", "got it", "thanks", "please", "go ahead", "sure"'


# ── Chat platform metaphor ─────────────────────────────────────────────────
# Used to tell the LLM "write like a chat message, not like email/novel".
# In Korean communities the reference point is KakaoTalk (카톡); Discord elsewhere.

def chat_platform_name() -> str:
    if _lang() == "ko":
        return "카톡"  # KakaoTalk
    return "Discord"


def chat_style_phrase() -> str:
    """Brief 'chat-style' descriptor — e.g. 'like KakaoTalk' vs 'Discord style'."""
    if _lang() == "ko":
        return "카톡처럼 짧은 메시지 여러 개로"
    return "Discord-style short messages across multiple lines"


# ── Group chat term ────────────────────────────────────────────────────────
# Korean has a distinctive colloquial term "톡방" for group-chat rooms.

def group_chat_term() -> str:
    if _lang() == "ko":
        return "톡방"
    return "group chat"


# ── Conversation closers ───────────────────────────────────────────────────
# Natural ways to end a conversation — LLM uses these to wrap naturally without drift.

def conversation_closer_examples() -> str:
    if _lang() == "ko":
        return "'이따 봐', '또 얘기하자', '수고해', '푹 쉬어'"
    return "'ttyl', 'catch you later', 'talk soon', 'take care'"


# ── Korean honorific / address conventions ─────────────────────────────────
# Non-Korean languages generally skip these entirely. Used in the tutorial greeting to guide
# first introduction — whether / when to ask about 오빠/언니/형/누나 style address.

def honorifics_convention_note() -> str:
    if _lang() == "ko":
        return (
            "한국어는 나이·관계에 따라 호칭(오빠/언니/형/누나)과 존댓말/반말이 달라진다. "
            "오너 확인 전엔 호칭 함부로 쓰지 말고, 친해지는 타이밍에 명확한 질문으로 허락 받기 "
            "(예: '오빠라고 불러도 돼요?' / '말 놓아도 될까요?')."
        )
    # English and most other languages don't have this layer.
    return ""


# ── Filler laugh / confirmation particles ──────────────────────────────────
# Helps LLM understand Korean "ㅋㅋ" / "ㅎㅎ" as non-content laughter rather than mistakes.

def filler_particles_note() -> str:
    if _lang() == "ko":
        return "'ㅋㅋ', 'ㅎㅎ', 'ㅠㅠ' 같은 자음 반복은 한국어 채팅의 자연스런 감정 표지 — 과하지 않게 적절히 사용."
    return ""


# ── Profile enum values (gender 등) — 커뮤니티 언어로 저장되어야 대시보드 UI 통일 ─
# LLM 이 create_agent_profile JSON 에 채울 때 영어 'female' 대신 한국어 '여자' 쓰도록 유도.

def gender_options() -> str:
    """agent profile JSON 의 gender 필드 허용값."""
    if _lang() == "ko":
        return "남자 | 여자 | 기타"
    return "male | female | other"


# ── Tutorial greeting: honorifics · speech-style block ────────────────────
# Used in `src.scenes.tutorial.greeting.build_yuna_greeting_prompt` — provides the whole
# Korean-specific "address / speech-level / casual-mode permission" coaching block. For
# non-ko languages a minimal address-style ask is returned instead.

def korean_tutorial_hints(
    name: str,
    age,
    gender: str,
    nickname: str,
    p_name: str,
    yuna_age: int,
    older: bool,
    lang: str | None = None,
) -> str:
    """Greeting-time coaching on honorifics + speech style.

    ko: full 호칭/존댓말/반말 coaching with concrete Korean examples.
    en (and others): generic ask-preferred-name + tone question.
    """
    eff = lang or _lang()
    if eff == "ko":
        closer_question = (
            "\n- IMPORTANT phrasing: ask these as clear questions, NOT as soft trailing statements.\n"
            "  나쁜 예(어색): \"오빠라고 불러도 되고요 ㅎㅎ\" (평서형 덧붙임)\n"
            "  좋은 예(자연): \"오빠라고 불러도 돼요?\" / \"혹시 오빠라고 불러도 괜찮아요?\"\n"
            "  말 놓기도 마찬가지: \"말 놓아도 될까요?\" / \"편하게 해도 돼요?\""
        )
        return (
            f"- {name} is {age} years old, gender={gender}. You ({p_name}) are {yuna_age}y/o female.\n"
            f"- {'Older than you — start with formal speech (존댓말).' if older else 'Similar age or unknown — start formal.'}\n"
            f"- You want to get closer. {'Ask if casual speech is okay. ' if older else ''}\n"
            f"- Honorific/호칭 suggestion — YOUR judgment based on owner's gender + age gap:\n"
            f"    older male → 오빠 가능, older female → 언니 가능, similar age → 이름/닉네임,\n"
            f"    younger owner → 이름 + 존댓말. 오너가 원치 않으면 본인이 원하는 호칭으로 조정.\n"
            f"\n"
            f"- ⚠ CRITICAL consistency rule:\n"
            f"  Until the owner confirms, DO NOT use 오빠/언니/형/누나 in any line of your greeting.\n"
            f"  Address them with 이름 or 별명 only (e.g., '{nickname or name}' or '{name}님').\n"
            f"  THEN at the end, ask permission: '오빠라고 불러도 돼요?' / '편하게 말 놓아도 돼요?'\n"
            f"  사용하면서 허락 구하는 것은 앞뒤 안 맞음 (큰 어색함).\n"
            f"- Ask their preferred speech style (formal/casual). This is required."
            f"{closer_question}"
        )
    # Generic (en, etc.): no honorific layer, just ask what they prefer.
    return (
        f"- Ask what they'd like to be called (first name / nickname / something else).\n"
        f"- Ask if they prefer casual or more polite tone."
    )


def tutorial_name_hint(name: str, lang: str | None = None) -> str:
    """How to address the user in the very first greeting."""
    eff = lang or _lang()
    if eff == "ko":
        return (
            f"Don't use full name ({name}). For Korean names, drop the surname "
            f"(e.g. 홍길동→길동). Be friendly."
        )
    return f"Use first name only from ({name}). Be friendly and casual."


# ── Persona first-greeting style hint ──────────────────────────────────────
# Injected into `persona_first_greeting_prompt`. Korean gets the 카톡 reference, others get
# a generic chat-app phrasing.

def new_friend_greet_style() -> str:
    if _lang() == "ko":
        return "카톡처럼. 네 말투로. 로봇 같은 정형화된 인사 금지."
    return "Chat-style, short lines in your own voice. No robotic or formulaic greetings."


# ── Feedback / alert headers (mgr_feedback) ────────────────────────────────
# Short bracketed tags that open an internal prompt to the mgr agent.

def request_alert_header() -> str:
    if _lang() == "ko":
        return "[요청 알림]"
    return "[Request alert]"


# ── Supervisor judge answer tokens ─────────────────────────────────────────
# Haiku judge returns ONE of these tokens. Downstream code pattern-matches on them
# (e.g. `if "멈춤" in judgment`). The *question* is in English but the expected answer
# vocabulary must stay in the community's language so caller checks still fire.

def chat_stuck_answer_tokens() -> str:
    if _lang() == "ko":
        return "'진행중' 또는 '멈춤:이름'"
    return "'ongoing' or 'stopped:<name>'"


def profile_collection_answer_tokens() -> str:
    if _lang() == "ko":
        return "'미응답', '잡담', '진행중'"
    return "'unanswered', 'chatting', 'ongoing'"


def creator_icebreak_answer_tokens() -> str:
    if _lang() == "ko":
        return "'충분', '진행중'"
    return "'enough', 'ongoing'"


# ── Sample names (for locale-appropriate examples in templates) ────────────
# Korean vs English/generic first-name examples — used in docstrings/examples only.

def sample_first_names() -> tuple[str, str, str]:
    if _lang() == "ko":
        return ("수연", "빈이", "해린")
    return ("sue", "bin", "haerin")
