"""Cross-scene Haiku judge question templates used by Supervisors.

Scene-specific judges live in each scene module (e.g. `src/scenes/tutorial/judge_prompts.py`).
This file only holds questions that are relevant across scenes (generic chat stall detection,
future retention / emotion supervisors etc.).

Questions are in English (prompt-engineering norm). The *expected answer tokens*
stay in the community's language because downstream code pattern-matches against them
(e.g. `if "멈춤" in judgment`). Locale helpers inject the right token list.
"""
from __future__ import annotations

from src.core.prompts.locale import chat_stuck_answer_tokens


# Callable (not constant) — answer tokens depend on the active community's language.

def CHAT_STUCK_QUESTION() -> str:  # noqa: N802 (kept uppercase to mirror old constant name)
    """General channel-conversation supervisor (src/supervisors/chat.py)."""
    tokens = chat_stuck_answer_tokens()
    return (
        "Is this conversation flowing naturally, or has one side stalled and it's stuck? "
        f"If stalled, who should speak next? Answer with one of: {tokens}."
    )


__all__ = ["CHAT_STUCK_QUESTION"]
