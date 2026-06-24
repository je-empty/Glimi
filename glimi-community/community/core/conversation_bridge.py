# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
conversation_bridge (core) — discord-free wiring for the kernel conversation engine.

Wires the pure kernel engine (``glimi.conversation``) to the Community app:
- injects the SQLite ``KernelStore`` + ``OwnerContext`` adapters,
- supplies a transport-neutral ``<tools>`` execution callback (resolved via
  ``get_channel_adapter()`` → ``core.mgr_actions.parse_and_execute_actions``),
- applies the app's maintenance guard.

This is the web home for ``start_conversation`` (the old ``community/bot/
conversation_bridge.py`` re-exports from here). NO ``import discord``.

The pure helpers (stop / list / detect / state) come straight from the kernel
module — they share the kernel's active-conversation state, so re-exporting them
here is identical to importing from the kernel directly.
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
from community.adapters.kernel_store import kernel_store, owner_context

__all__ = [
    "start_conversation",
    "stop_conversation",
    "list_active_conversations",
    "get_active_conversation",
    "detect_room_request",
    "ConversationState",
]


async def _execute_agent_tools(channel_name: str, speaker_id: str) -> None:
    """Run any ``<tools>`` a just-spoken agent emitted, against the resolved adapter.

    SECOND feeder of the kernel tool stash (the first is ``chat._run_turn``). It
    MUST run inside the same active-community scope as the stash write — the engine
    drives both within one ``run_in_community`` turn, so ``pop_tool_calls`` keys
    consistently (Phase 3.0). Resolves the transport via ``get_channel_adapter()``
    so it is discord-free on web.
    """
    from community.core.channel_adapter import get_channel_adapter
    from community.core.mgr_actions import parse_and_execute_actions

    channels = get_channel_adapter()
    await parse_and_execute_actions(
        channel_name, [], channels=channels, caller_agent_id=speaker_id
    )


async def start_conversation(
    channel_name: str,
    participants: list[str],
    send_fn: Callable[[str, str], Awaitable[None]],
    context: str = "",
    max_turns: int = _kc.DEFAULT_MAX_TURNS,
) -> ConversationState:
    """App-facing entry: maintenance guard + dependency injection, then run."""
    from community.community import is_maintenance_mode
    if is_maintenance_mode():
        from community import log_writer
        log_writer.system(f"[maintenance] start_conversation skip #{channel_name}")
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
