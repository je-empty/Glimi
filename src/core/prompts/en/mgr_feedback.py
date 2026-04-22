"""mgr / creator inline prompt bundle.

Extracted from src/bot/mgr_system.py (Phase 2-B pure move). English template kept
platform-neutral; locale helpers inject culture-specific terms (group-chat word etc.).

Builders:
  - persona_first_greeting_prompt: a new persona greeting the owner in their dm channel
  - conversation_report_prompt:    Yuna reports a finished auto-conversation to the owner
  - room_request_notify_prompt:    agent's group-chat request notification
  - action_notify_dm_prompt:       DM ACTION approval notice
  - action_notify_room_prompt:     group-chat ACTION approval notice
  - action_notify_generic_prompt:  other ACTION approval notice
"""
from __future__ import annotations

from src.core.prompts.locale import (
    group_chat_term,
    new_friend_greet_style,
    request_alert_header,
)


def conversation_report_prompt(
    names: list[str],
    channel: str,
    turn_count: int,
    preview: str,
    oc: str,
) -> str:
    """Yuna reports a finished auto-conversation to the owner and considers follow-up.

    Args:
        names: participating agent names
        channel: channel name where the conversation happened
        turn_count: number of turns
        preview: last-messages preview
        oc: owner address term
    """
    return (
        f"{', '.join(names)} finished talking in #{channel} ({turn_count} turns).\n"
        f"Last exchange:\n{preview}\n\n"
        f"Give {oc} a brief report.\n"
        f"If anyone in the conversation said they'd contact {oc} or tried to reach another person, "
        f"use the `start_conversation` tool to hand the thread off.\n"
        f"NEVER force-inject utterances into an agent (no arbitrary speech injection)."
    )


def room_request_notify_prompt(agent_name: str, message: str) -> str:
    """Notify Yuna that an agent requested a group-chat room.

    Args:
        agent_name: requesting agent
        message: snippet of the request
    """
    term = group_chat_term()
    return (
        f"{agent_name} seems to want a {term}. "
        f"Message: \"{message[:60]}\"\n"
        f"Create it with the `create_room` tool if it makes sense."
    )


def _action_judge_guide(oc: str) -> str:
    return (
        "Judgment rules:\n"
        f"- If the request is natural, approve it and give {oc} a brief report "
        f"(e.g. 'Seo-yeon wanted to DM So-yul, so I approved it').\n"
        f"- If it's unusual or unclear, DON'T reject — ask {oc} first "
        f"(e.g. '{oc}, should I approve this?')."
    )


def action_notify_dm_prompt(
    agent_name: str,
    agent_id: str,
    target_name: str,
    dm_message: str,
    oc: str,
) -> str:
    """Persona DM-request notice to Yuna. DM is auto-executed so this is informational."""
    return (
        f"{request_alert_header()}\n"
        f"{agent_name} sent a DM to {target_name}:\n"
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
    """Persona group-chat request notice to Yuna. On approval, call `create_room`."""
    term = group_chat_term()
    return (
        f"{request_alert_header()}\n"
        f"{agent_name} wants to open a {term}:\n"
        f"  Participants: {room_info}\n"
        f"  First message: \"{first_msg[:100]}\"\n\n"
        f"If you approve, create it with the `create_room` tool "
        f"(args: name / participants / first_message).\n"
        f"{_action_judge_guide(oc)}"
    )


def action_notify_generic_prompt(
    agent_name: str,
    action_str: str,
    oc: str,
) -> str:
    """Generic action-request notice to Yuna."""
    return (
        f"{request_alert_header()}\n"
        f"{agent_name} requested an action:\n"
        f"  -> {action_str}\n\n"
        f"To approve, call the tool that fits the situation.\n"
        f"{_action_judge_guide(oc)}"
    )


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
