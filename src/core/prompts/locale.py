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
# Non-Korean languages generally skip these entirely. Used in onboarding to guide first
# introduction — whether / when to ask about 오빠/언니/형/누나 style address.

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
