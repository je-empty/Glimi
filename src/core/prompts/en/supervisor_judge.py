"""Haiku judge question templates used by Supervisors.

Extracted from src/supervisors/chat.py + src/scenes/tutorial/supervisor.py
(Phase 2-B pure move). Each judge shows Haiku a recent-conversation summary and
asks for a one-word verdict — this module provides the question strings.

Questions are in English (prompt-engineering norm). The *expected answer tokens*
stay in the community's language because downstream code pattern-matches against
them (e.g. `if "멈춤" in judgment`). Locale helpers inject the right token list.
"""
from __future__ import annotations

from src.core.prompts.locale import (
    chat_stuck_answer_tokens,
    profile_collection_answer_tokens,
    creator_icebreak_answer_tokens,
)


# Exposed as callables because the returned answer tokens depend on the active
# community's language. Callers should do e.g. `CHAT_STUCK_QUESTION()`.

def CHAT_STUCK_QUESTION() -> str:  # noqa: N802 (kept uppercase to mirror old constant name)
    """General channel-conversation supervisor (src/supervisors/chat.py)."""
    tokens = chat_stuck_answer_tokens()
    return (
        "Is this conversation flowing naturally, or has one side stalled and it's stuck? "
        f"If stalled, who should speak next? Answer with one of: {tokens}."
    )


def TUTORIAL_PROFILE_COLLECTION_QUESTION() -> str:  # noqa: N802
    """Tutorial: user spoke but agent hasn't reacted / drifted into small talk."""
    tokens = profile_collection_answer_tokens()
    return (
        "Look at the recent conversation and judge: "
        "did the user just speak and the agent has not reacted yet? "
        "Or has it drifted into small talk so profile collection isn't progressing? "
        f"Answer with one of: {tokens}."
    )


def TUTORIAL_CREATOR_ICEBREAK_QUESTION() -> str:  # noqa: N802
    """Tutorial: has the creator icebroken enough / reached agent creation?"""
    tokens = creator_icebreak_answer_tokens()
    return (
        "Has the creator icebroken enough? Has it progressed to agent creation? "
        f"Answer with one of: {tokens}."
    )


__all__ = [
    "CHAT_STUCK_QUESTION",
    "TUTORIAL_PROFILE_COLLECTION_QUESTION",
    "TUTORIAL_CREATOR_ICEBREAK_QUESTION",
]
