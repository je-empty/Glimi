"""App bridge for the kernel conversation engine.

Wires the pure kernel engine (``glimi.conversation``) to the Community app:
- injects the SQLite ``KernelStore`` + ``OwnerContext`` adapters,
- supplies the Discord ``<tools>`` execution callback,
- applies the app's maintenance guard.

Callers import the conversation API from here (one site). The pure helpers
(stop / list / detect / state) are re-exported unchanged — they share the
kernel module's active-conversation state.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from glimi import conversation as _kc
from glimi.conversation import (  # re-export pure helpers
    ConversationState,
    detect_room_request,
    get_active_conversation,
    list_active_conversations,
    stop_conversation,
)
from src.adapters.kernel_store import kernel_store, owner_context

__all__ = [
    "start_conversation",
    "stop_conversation",
    "list_active_conversations",
    "get_active_conversation",
    "detect_room_request",
    "ConversationState",
]


async def _execute_agent_tools(channel_name: str, speaker_id: str) -> None:
    """Run any ``<tools>`` a just-spoken agent emitted, against the Discord channel.

    Lazy imports avoid a module-level import cycle with ``mgr_system``.
    """
    from src.bot.mgr_system import parse_and_execute_actions
    from src.bot.core import get_target_guild
    import discord

    guild = get_target_guild()
    if not guild:
        return
    ch_obj = discord.utils.get(guild.text_channels, name=channel_name)
    if not ch_obj:
        return
    await parse_and_execute_actions(ch_obj, [], guild, caller_agent_id=speaker_id)


async def start_conversation(
    channel_name: str,
    participants: list[str],
    send_fn: Callable[[str, str], Awaitable[None]],
    context: str = "",
    max_turns: int = _kc.DEFAULT_MAX_TURNS,
) -> ConversationState:
    """App-facing entry: maintenance guard + dependency injection, then run."""
    from src.community import is_maintenance_mode
    if is_maintenance_mode():
        from src import log_writer
        log_writer.system(f"[maintenance] start_conversation skip #{channel_name}")
        # 최소 state 리턴 (호출자 기대 타입 유지)
        return ConversationState(channel_name, participants, max_turns=max_turns)

    return await _kc.start_conversation(
        channel_name,
        participants,
        send_fn,
        store=kernel_store,
        owner=owner_context,
        execute_tools_fn=_execute_agent_tools,
        context=context,
        max_turns=max_turns,
    )
