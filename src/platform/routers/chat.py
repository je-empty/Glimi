"""Web-chat WebSocket adapter — the ``src/adapters/web_chat`` seam.

ONE WebSocket endpoint that bridges the platform-neutral kernel chat brain
(:meth:`AgentRuntime.generate_response_streaming`) to a browser over a socket.
This is a NEW adapter layer: it lives in ``src/platform`` (app side), imports the
kernel via the discord-free shim ``src.core.runtime``, and contains NO Discord
imports / types.

Phase 1 scope (stub-quality, intentionally small):
- auth at connect time (cookie → ``verify_session`` → ``user_can_access``) BEFORE
  ``accept()``;
- a :class:`WebOutbox` implementing :class:`glimi.transport.Outbox`, serializing
  frames over the socket via :mod:`chat_hub`;
- a dispatcher that rejects non-user-postable channels and otherwise streams an
  echo reply back line-by-line.

No debounce / interrupt / image handling yet (Phase 3/4).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from glimi.transport import ImagePart, Outbox, Speaker

from .. import accounts
from ..config import SESSION_COOKIE_NAME
from ..sessions import verify_session
from .. import chat_hub
from src.core.channels import is_user_postable

router = APIRouter()


class WebOutbox(Outbox):
    """:class:`glimi.transport.Outbox` that serializes turns as JSON frames and
    broadcasts them to every connection watching ``(community_id, channel_id)``.

    Frame shapes (all carry ``type`` + ``channel``):
      - ``{type:'text',    channel, agent_id, speaker, text}``
      - ``{type:'typing',  channel, agent_id, speaker, on}``
      - ``{type:'image',   channel, agent_id, speaker, url, caption}``
      - ``{type:'interrupted', channel, agent_id, speaker}``
    """

    def __init__(self, community_id: str):
        self.community_id = community_id

    async def _broadcast(self, channel_id: str, frame: dict) -> str:
        frame.setdefault("channel", channel_id)
        await chat_hub.broadcast(self.community_id, channel_id, frame)
        return ""

    async def send_text(self, channel_id: str, speaker: Speaker, text: str) -> str:
        return await self._broadcast(channel_id, {
            "type": "text",
            "agent_id": speaker.agent_id,
            "speaker": speaker.display_name,
            "text": text,
        })

    async def send_image(self, channel_id: str, speaker: Speaker, image: ImagePart) -> str:
        return await self._broadcast(channel_id, {
            "type": "image",
            "agent_id": speaker.agent_id,
            "speaker": speaker.display_name,
            "url": image.url or "",
            "caption": image.caption,
        })

    async def set_typing(self, channel_id: str, speaker: Speaker, on: bool) -> None:
        await self._broadcast(channel_id, {
            "type": "typing",
            "agent_id": speaker.agent_id,
            "speaker": speaker.display_name,
            "on": bool(on),
        })

    async def notify_interrupted(self, channel_id: str, speaker: Speaker) -> None:
        await self._broadcast(channel_id, {
            "type": "interrupted",
            "agent_id": speaker.agent_id,
            "speaker": speaker.display_name,
        })


def _authenticate(websocket: WebSocket, community_id: str) -> Optional[dict]:
    """Resolve the platform login user from the session cookie and verify
    per-community access. Returns the user dict or None (caller rejects)."""
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session(token) if token else None
    if not user_id:
        return None
    user = accounts.get_user_by_id(user_id)
    if not user:
        return None
    if not accounts.user_can_access(user, community_id):
        return None
    return user


def _resolve_speaker(agent_id: str) -> Speaker:
    """Build the outbound :class:`Speaker` for an agent (must run inside an active
    community scope so display-name lookup hits the right DB)."""
    display = agent_id
    try:
        from src.core import profile as _profile
        display = _profile.get_agent_display_name(agent_id) or agent_id
    except Exception:
        pass
    return Speaker(agent_id=agent_id, display_name=display)


def _resolve_owner_speaker_id() -> str:
    """The community owner id the kernel logs the human turn under (default
    'owner'). Must run inside an active community scope."""
    try:
        from src.core import profile as _profile
        return _profile.get_user_id()
    except Exception:
        return "owner"


async def _run_turn(
    *, community_id: str, channel_id: str, agent_id: str, text: str,
    outbox: WebOutbox,
) -> None:
    """Stream one agent turn back over the socket using the ECHO backend.

    The kernel streaming call is BLOCKING, so it runs in an executor thread and
    bridges its synchronous ``on_message`` callback onto the event loop via an
    asyncio.Queue (the Discord handler pattern). Each emitted line is broadcast
    as a 'text' frame; typing is driven from this turn's lifecycle.
    """
    # Echo backend — zero cost, no network. Set before the first runtime call.
    os.environ.setdefault("GLIMI_LLM_BACKEND", "echo")

    from src.core.runtime import runtime
    from src.platform.community_ctx import run_in_community

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    def _on_message(msg: str) -> None:
        # Synchronous kernel callback → hop back onto the loop.
        loop.call_soon_threadsafe(queue.put_nowait, msg)

    def _generate():
        # Scope the community inside the worker thread; the kernel reads
        # process-global state guarded by the community lock.
        def _call():
            return runtime.generate_response_streaming(
                agent_id, channel_id, text, on_message=_on_message,
            )
        try:
            run_in_community(community_id, _call)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    # Resolve the outbound speaker inside the community scope.
    speaker = run_in_community(community_id, lambda: _resolve_speaker(agent_id))

    await outbox.set_typing(channel_id, speaker, True)
    fut = loop.run_in_executor(None, _generate)
    lines: list[str] = []
    try:
        while True:
            item = await asyncio.wait_for(queue.get(), timeout=60.0)
            if item is SENTINEL:
                break
            lines.append(item)
            await outbox.send_text(channel_id, speaker, item)
    except asyncio.TimeoutError:
        await outbox.send_text(channel_id, speaker, "[오류] 응답 시간이 초과되었습니다.")
    finally:
        await outbox.set_typing(channel_id, speaker, False)
        try:
            await fut
        except Exception:
            pass

    # The kernel does NOT persist the agent's reply (only the owner turn) — log
    # each line here so chat history shows both sides.
    if lines:
        def _persist():
            from src import db
            for ln in lines:
                try:
                    db.log_message(channel_id, agent_id, ln)
                except Exception:
                    break
        try:
            await loop.run_in_executor(None, lambda: run_in_community(community_id, _persist))
        except Exception:
            pass


@router.websocket("/community/{cid}/chat/ws")
async def chat_ws(websocket: WebSocket, cid: str):
    """Web-chat WebSocket. Inbound text frame shape:
    ``{type:'text', channel, agent, text}``. Server emits 'text'/'typing'/
    'image'/'interrupted'/'error' frames."""
    user = _authenticate(websocket, cid)
    if user is None:
        # Reject BEFORE accept — 1008 = policy violation.
        await websocket.close(code=1008)
        return

    await websocket.accept()
    outbox = WebOutbox(cid)
    joined: set[str] = set()  # channels this socket is registered for

    try:
        while True:
            frame = await websocket.receive_json()
            ftype = (frame.get("type") or "text").strip()
            channel_id = (frame.get("channel") or "").strip()
            agent_id = (frame.get("agent") or "mgr").strip()

            if not channel_id:
                await websocket.send_json({"type": "error", "error": "missing channel"})
                continue

            # Register this connection for the channel so broadcasts reach it.
            if channel_id not in joined:
                await chat_hub.register(cid, channel_id, websocket)
                joined.add(channel_id)

            if ftype == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if ftype != "text":
                await websocket.send_json({"type": "error", "error": f"unknown frame type: {ftype}"})
                continue

            text = (frame.get("text") or "").strip()
            if not text:
                await websocket.send_json({"type": "error", "error": "empty text"})
                continue

            # Reject internal/system channels — only dm-*/group-* accept input.
            if not is_user_postable(channel_id):
                await websocket.send_json({
                    "type": "error",
                    "channel": channel_id,
                    "error": "channel is not user-postable",
                })
                continue

            await _run_turn(
                community_id=cid, channel_id=channel_id,
                agent_id=agent_id, text=text, outbox=outbox,
            )
    except WebSocketDisconnect:
        pass
    finally:
        for ch in joined:
            await chat_hub.unregister(cid, ch, websocket)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass
