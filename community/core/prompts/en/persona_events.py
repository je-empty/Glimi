"""Prompts injected into a persona agent on lifecycle events.

Target: persona agent (the new character the user just met).
Distinct from `mgr_notifications.py` which targets the mgr (Yuna).
"""
from __future__ import annotations

from community.core.prompts.locale import new_friend_greet_style


def persona_first_greeting_prompt(
    dm_name: str,
    call: str,
) -> str:
    """A newly-created persona agent greeting the owner in its dm channel for the first time.

    Args:
        dm_name: channel name (e.g. 'dm-sue')
        call: owner address term (nickname preferred, else name)
    """
    style_hint = new_friend_greet_style()
    return (
        f"[Situation] This channel (#{dm_name}) is just you and {call}. "
        f"{call} has just arrived and you two are chatting for the first time.\n"
        f"[Direction] Greet {call} naturally. Let your personality / background come through "
        f"in 2-4 short chat messages. Brief self-intro + one light remark (a question or how-are-you).\n"
        f"[IMPORTANT] No meta statements. Do NOT use any of these:\n"
        f"  - 'I was just made' / 'someone created me' / 'I was designed'\n"
        f"  - Names like 'Hana' / 'Yuna' / 'Creator' / 'mgr' / anyone else outside this channel\n"
        f"  - 'agent' / 'bot' / 'character' / 'AI' / 'system' / 'what is this place'\n"
        f"You are just an ordinary person saying hi to {call}, whom you're meeting for the first time.\n"
        f"[Style] {style_hint}\n"
        f"[Forbidden] Do not use the <tools> block. Chat-only greeting for now."
    )


__all__ = ["persona_first_greeting_prompt"]
