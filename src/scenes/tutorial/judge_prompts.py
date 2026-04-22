"""Tutorial scene — Haiku judge questions used by TutorialFlowSupervisor.

Scene-local: only relevant while the tutorial scene is active. Moved from
`src/core/prompts/en/supervisor_judge.py` to keep scene-specific prompts with the
scene module (pattern: every scene carries its own `judge_prompts.py` if needed).

General (cross-scene) judges stay in `src/core/prompts/en/supervisor_judge.py`.

Questions are in English (prompt-engineering norm). The expected answer tokens stay
in the community's language because downstream code pattern-matches against them
(e.g. `if "멈춤" in judgment`). Locale helpers inject the right token list.
"""
from __future__ import annotations

from src.core.prompts.locale import (
    creator_icebreak_answer_tokens,
    profile_collection_answer_tokens,
)


# Callables (not constants) — answer tokens depend on the active community's language.

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
    "TUTORIAL_PROFILE_COLLECTION_QUESTION",
    "TUTORIAL_CREATOR_ICEBREAK_QUESTION",
]
