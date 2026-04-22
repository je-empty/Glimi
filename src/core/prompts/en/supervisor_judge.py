"""Supervisor 용 Haiku judge 질문 템플릿.

src/supervisors/chat.py + src/scenes/tutorial/supervisor.py 에서 분리됨
(Phase 2-B pure move). 각 judge 는 Haiku 에게 최근 대화 요약을 보여주고
한 단어 판정을 받는 구조 — 이 파일은 "question" 문자열만 제공.
"""
from __future__ import annotations


# ── chat.py (범용 채널 대화 감시) ────────────────────────

CHAT_STUCK_QUESTION = (
    "이 대화가 자연스럽게 이어지고 있나, 아니면 한쪽이 멈춰서 안 되고 있나? "
    "멈춤이면 누가 다음에 말해야 하나? '진행중', '멈춤:에이전트이름' 중 하나로."
)


# ── tutorial/supervisor.py ──────────────────────────────

TUTORIAL_PROFILE_COLLECTION_QUESTION = (
    "최근 대화를 보고 판단해줘. "
    "유저가 마지막에 말했는데 에이전트가 아직 반응하지 않은 건가? "
    "아니면 잡담으로 빠져서 프로필 수집이 진행되지 않는 건가? "
    "'미응답', '잡담', '진행중' 중 하나로."
)

TUTORIAL_CREATOR_ICEBREAK_QUESTION = (
    "크리에이터가 아이스브레이킹을 충분히 했나? "
    "에이전트 생성까지 진행됐나? "
    "'충분', '진행중' 중 하나로."
)


__all__ = [
    "CHAT_STUCK_QUESTION",
    "TUTORIAL_PROFILE_COLLECTION_QUESTION",
    "TUTORIAL_CREATOR_ICEBREAK_QUESTION",
]
