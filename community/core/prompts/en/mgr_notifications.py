"""Prompts injected into the mgr (Yuna) on cross-agent notifications.

Target: mgr agent (Yuna) — she reads the prompt and decides to act.

Scope:
  - conversation_report_prompt:    auto-conversation ended, report to owner
  - room_request_notify_prompt:    agent wants a group chat room
  - action_notify_dm_prompt:       persona DM action notice (auto-executed, informational)
  - action_notify_room_prompt:     persona group-chat action needs approval
  - action_notify_generic_prompt:  other action approvals
"""
from __future__ import annotations

from community.core.prompts.locale import (
    group_chat_term,
    request_alert_header,
)


def conversation_report_prompt(
    names: list[str],
    channel: str,
    turn_count: int,
    preview: str,
    oc: str,
) -> str:
    """Yuna reports a finished auto-conversation to the owner and considers follow-up."""
    return (
        f"{', '.join(names)} finished talking in #{channel} ({turn_count} turns).\n"
        f"Last exchange:\n{preview}\n\n"
        f"Give {oc} a brief report.\n"
        f"If anyone in the conversation said they'd contact {oc} or tried to reach another person, "
        f"use the `start_conversation` tool to hand the thread off.\n"
        f"NEVER force-inject utterances into an agent (no arbitrary speech injection)."
    )


def room_request_notify_prompt(agent_name: str, message: str) -> str:
    """Notify Yuna that an agent requested a group-chat room."""
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


__all__ = [
    "conversation_report_prompt",
    "room_request_notify_prompt",
    "action_notify_dm_prompt",
    "action_notify_room_prompt",
    "action_notify_generic_prompt",
]
