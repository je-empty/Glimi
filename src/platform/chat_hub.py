"""In-process web-chat connection registry.

Maps ``(community_id, channel_id)`` to the set of live WebSocket connections and
broadcasts JSON frames to all of them. Dependency-light: it only needs the
WebSocket object's ``send_json`` method, so it stays trivially testable and does
not import FastAPI types at module scope beyond the loose ``Any`` typing.

This is the web equivalent of the Discord "outbox" — the place a turn lands so
every connected viewer of a channel sees it. It is deliberately tiny; debounce,
backpressure, and reconnection are later phases.
"""
from __future__ import annotations

import asyncio
from typing import Any

# (community_id, channel_id) -> set of connections
_ROOMS: dict[tuple[str, str], set[Any]] = {}
_LOCK = asyncio.Lock()


def _key(community_id: str, channel_id: str) -> tuple[str, str]:
    return (community_id or "", channel_id or "")


async def register(community_id: str, channel_id: str, ws: Any) -> None:
    """Add a connection to a room."""
    async with _LOCK:
        _ROOMS.setdefault(_key(community_id, channel_id), set()).add(ws)


async def unregister(community_id: str, channel_id: str, ws: Any) -> None:
    """Remove a connection; drops the room when it empties."""
    async with _LOCK:
        k = _key(community_id, channel_id)
        room = _ROOMS.get(k)
        if room is None:
            return
        room.discard(ws)
        if not room:
            _ROOMS.pop(k, None)


async def broadcast(community_id: str, channel_id: str, frame: dict) -> None:
    """Send ``frame`` (a JSON-serializable dict) to every connection in the room.

    Dead connections (whose ``send_json`` raises) are pruned. Snapshots the room
    under the lock, then sends outside it so a slow socket can't block others.
    """
    async with _LOCK:
        targets = list(_ROOMS.get(_key(community_id, channel_id), ()))
    if not targets:
        return
    dead: list[Any] = []
    for ws in targets:
        try:
            await ws.send_json(frame)
        except Exception:
            dead.append(ws)
    if dead:
        async with _LOCK:
            room = _ROOMS.get(_key(community_id, channel_id))
            if room is not None:
                for ws in dead:
                    room.discard(ws)
                if not room:
                    _ROOMS.pop(_key(community_id, channel_id), None)


def connection_count(community_id: str, channel_id: str) -> int:
    """Live connection count for a room (test/introspection helper)."""
    return len(_ROOMS.get(_key(community_id, channel_id), ()))
