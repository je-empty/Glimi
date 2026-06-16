"""Web-chat adapter — the ``src/adapters/web_chat`` seam.

A WebSocket endpoint plus a couple of read-only REST endpoints that bridge the
platform-neutral kernel chat brain (:meth:`AgentRuntime.generate_response_streaming`)
to a browser. This is a NEW adapter layer: it lives in ``src/platform`` (app
side), imports the kernel via the discord-free shim ``src.core.runtime``, and
contains NO Discord imports / types.

Phase 2 scope (real chat, single-owner):
- auth at connect time (cookie → ``verify_session`` → ``user_can_access``) BEFORE
  ``accept()`` for the socket, and ``require_user`` + per-community access for the
  REST endpoints;
- a :class:`WebOutbox` implementing :class:`glimi.transport.Outbox`, serializing
  frames over the socket via :mod:`chat_hub`;
- a dispatcher that rejects non-user-postable channels and otherwise streams a
  REAL turn using **each agent's CONFIGURED backend** (config-layering) — it does
  NOT force any backend. The community's per-community LLM-routing env keys are
  loaded from ``communities/{cid}/.env`` into ``os.environ`` *inside the
  community scope* (via the kernel's canonical reader) so the kernel's provider
  resolution sees them — Phase-1's ``_apply_community`` switches DB/caches but
  does NOT load the community ``.env``;
- a channel-list endpoint (DM-per-agent + groups) and a history cold-load
  endpoint, both community-scoped via :mod:`community_ctx`.

Single-owner v1: the inbound author is always the community owner
(``profile.get_user_id``); there is no per-connection identity. No debounce /
interrupt / image handling yet (Phase 3/4); no multi-agent group fan-out yet
(Phase 3 — a group channel currently runs the single ``agent`` on the frame).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect, WebSocketState

from glimi.transport import ImagePart, Outbox, Speaker

from .. import accounts
from ..auth import get_current_user
from ..config import SESSION_COOKIE_NAME
from ..sessions import verify_session
from .. import chat_hub
from src.core.channels import channel_kind, is_user_postable

router = APIRouter()


class WebOutbox(Outbox):
    """:class:`glimi.transport.Outbox` that serializes turns as JSON frames and
    broadcasts them to every connection watching ``(community_id, channel_id)``.

    Frame shapes (all carry ``type`` + ``channel``):
      - ``{type:'text',    channel, id, agent_id, speaker, text, reply_to?, client_msg_id?}``
      - ``{type:'typing',  channel, agent_id, speaker, on}``
      - ``{type:'image',   channel, id, agent_id, speaker, url, caption}``
      - ``{type:'interrupted', channel, agent_id, speaker}``
      - ``{type:'reaction'|'reaction_removed', channel, id, actor_id, actor_name, emoji, count}``
      - ``{type:'thread',  channel, root, messages:[...]}``

    The ``text``/``image`` frames carry the persisted message ``id`` (from
    ``db.log_message``'s ``lastrowid``) so the client can anchor reactions /
    reply quotes on the rendered row, and an optional ``client_msg_id`` so the
    sender's optimistic bubble reconciles instead of duplicating.
    """

    def __init__(self, community_id: str):
        self.community_id = community_id

    async def _broadcast(self, channel_id: str, frame: dict) -> str:
        frame.setdefault("channel", channel_id)
        await chat_hub.broadcast(self.community_id, channel_id, frame)
        return str(frame.get("id") or "")

    async def send_text(self, channel_id: str, speaker: Speaker, text: str,
                        *, message_id: Optional[int] = None,
                        reply_to: Optional[int] = None,
                        client_msg_id: str = "") -> str:
        frame = {
            "type": "text",
            "id": message_id,
            "agent_id": speaker.agent_id,
            "speaker": speaker.display_name,
            "text": text,
        }
        if reply_to is not None:
            frame["reply_to"] = reply_to
        if client_msg_id:
            frame["client_msg_id"] = client_msg_id
        return await self._broadcast(channel_id, frame)

    async def send_image(self, channel_id: str, speaker: Speaker, image: ImagePart,
                         *, message_id: Optional[int] = None) -> str:
        return await self._broadcast(channel_id, {
            "type": "image",
            "id": message_id,
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

    async def emit_reaction(self, channel_id: str, *, message_id: int,
                            actor_id: str, actor_name: str, emoji: str,
                            count: int, removed: bool = False) -> None:
        """Broadcast a reaction add/remove for ``message_id`` to the room.

        ``count`` is the post-mutation total for ``emoji`` on that message so the
        client can reconcile its optimistic pill against the authoritative count.
        """
        await self._broadcast(channel_id, {
            "type": "reaction_removed" if removed else "reaction",
            "id": message_id,
            "actor_id": actor_id,
            "actor_name": actor_name,
            "emoji": emoji,
            "count": count,
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


def _api_user(request: Request, community_id: str) -> dict:
    """API-style auth for the REST chat endpoints: JSON 401/403, never an HTML
    redirect. These return JSON, so a browser ``fetch`` must get a clean status
    code (``require_user`` 307-redirects browser requests to /login, which a
    fetch would receive as HTML)."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(status_code=403, detail="no access to this community")
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


def _load_community_llm_env() -> None:
    """Load the active community's LLM provider keys from its ``.env`` into
    ``os.environ`` (override) so the kernel's provider resolution picks up the
    CONFIGURED backend (config-layering).

    Must run INSIDE an active community scope. Reuses the kernel's canonical
    community-LLM-env reader (``monitor._community_llm_env`` — the single source
    of truth for *which* keys are LLM-routing keys), so only the LLM-routing keys
    are touched — never the whole ``.env`` — to avoid clobbering platform-wide
    env (Discord tokens, session secrets, data dir). This mirrors the effect of
    ``src/bot/__init__.py``'s ``load_dotenv(get_env_path(), override=True)`` for
    the keys that matter, without importing ``src.bot`` (it pulls
    ``import discord``).

    Keys absent from the community ``.env`` are left untouched in ``os.environ``
    (the kernel then falls through its default provider chain, e.g. claude) —
    this never *injects* a forced backend of its own.
    """
    try:
        from src.core import monitor as _monitor
        for key, val in _monitor._community_llm_env().items():
            if val is not None:
                os.environ[key] = val
    except Exception:
        # A missing/unreadable .env is fine — leave os.environ as-is.
        pass


def _resolve_responding_agent(channel_id: str, frame_agent: str) -> str:
    """Resolve which agent answers a user turn on ``channel_id``.

    Web convention (asymmetric vs Discord — do NOT reuse CHANNEL_AGENT_MAP):
      - ``dm-<agent_id>``: the channel's agent answers. The frame carries the
        agent explicitly; fall back to deriving it from the channel id.
      - ``group-*``: v1 runs the single ``agent`` from the frame. Full
        multi-agent group fan-out (Discord's ``GROUP_PARTICIPANTS`` + parallel
        ``_process_agent``) is NOT ported yet — that is Phase 3. If the frame has
        no agent for a group, fall back to ``mgr`` so we never crash.
    """
    agent = (frame_agent or "").strip()
    if agent:
        return agent
    kind = channel_kind(channel_id)
    if kind == "dm" and channel_id.startswith("dm-"):
        derived = channel_id[len("dm-"):].strip()
        if derived:
            return derived
    # group / unknown without an explicit agent → mgr (never crash on a group).
    return "mgr"


def _agent_exists(community_id: str, agent_id: str) -> bool:
    """True iff ``agent_id`` is a real agent in this community. Scopes the
    community for the lookup (the read API is global-DB-path based)."""
    if not agent_id:
        return False

    def _check() -> bool:
        try:
            from src import db
            return db.get_agent(agent_id) is not None
        except Exception:
            return False

    try:
        from src.platform.community_ctx import run_in_community
        return run_in_community(community_id, _check)
    except Exception:
        return False


# ── read APIs (channel list + history) — community-scoped ──────────────

def _list_postable_channels(community_id: str) -> list[dict]:
    """The owner's user-postable channels for this community.

    DMs are synthesized per agent as ``dm-<agent_id>`` (the web convention,
    matching pages.py / chat.js) with display name + avatar url. Group channels
    are taken from the registered channel list, filtered to ``group-*`` (the
    only registered channels a user may post into). ``mgr-*`` / ``internal-*``
    are EXCLUDED (not user-postable).
    """
    def _query() -> list[dict]:
        from src import db
        out: list[dict] = []
        # DM-per-agent. Order: mgr → creator → dev → persona, then by id.
        try:
            agents = db.list_agents()
        except Exception:
            agents = []
        type_rank = {"mgr": 0, "creator": 1, "dev": 2, "persona": 3}
        agents.sort(key=lambda a: (type_rank.get(a.get("type", ""), 9), a.get("id", "")))
        for a in agents:
            aid = a.get("id")
            if not aid:
                continue
            out.append({
                "channel": f"dm-{aid}",
                "kind": "dm",
                "agent_id": aid,
                "name": a.get("name") or aid,
                "type": a.get("type", ""),
                "avatar_url": f"/api/avatar?community={community_id}&id={aid}",
            })
        # Registered group channels (user-postable, multi-agent). Exclude
        # mgr-/internal-/dm- via is_user_postable + explicit group prefix.
        try:
            from src.core import monitor
            channels = monitor.get_channels()
        except Exception:
            channels = []
        for ch in channels:
            name = ch.get("name") or ""
            if not name.startswith("group-"):
                continue
            if not is_user_postable(name):
                continue
            out.append({
                "channel": name,
                "kind": "group",
                "agent_id": None,
                "name": name,
                "type": "group",
                "avatar_url": None,
            })
        return out

    from src.platform.community_ctx import run_in_community
    return run_in_community(community_id, _query)


def _channel_history(community_id: str, channel_id: str, limit: int) -> list[dict]:
    """Recent messages for ``channel_id``, ASC (newest-last), display-ready.

    Uses the display-resolving read API (``monitor.get_recent_messages``) so the
    speaker is resolved to a name and ``is_user`` flags the bubble side. Each row
    also carries ``reactions`` (a compact emoji/count summary folded in by the
    read API) and ``reply_to`` (a ``{id, preview, author}`` context resolved from
    the parent row when one is in the loaded window, else ``{id}``) so a
    cold-loaded message shows the SAME affordances as a live frame — ONE client
    contract for history + WS.
    """
    def _query() -> list[dict]:
        from src.core import monitor
        rows = monitor.get_recent_messages(limit=limit, channel=channel_id)
        # Index rows by id so a reply can resolve its parent's preview/author
        # from the already-loaded window (no extra query for the common case).
        by_id = {r.get("id"): r for r in rows if r.get("id") is not None}
        out: list[dict] = []
        for r in rows:
            reply_to = None
            parent_id = r.get("reply_to")
            if parent_id is not None:
                parent = by_id.get(parent_id)
                if parent is not None:
                    reply_to = {
                        "id": parent_id,
                        "author": parent.get("speaker") or "",
                        "author_id": parent.get("speaker_id") or "",
                        "is_user": bool(parent.get("is_user")),
                        "preview": (parent.get("message") or "")[:120],
                    }
                else:
                    # Parent is outside the loaded window — keep the pointer so the
                    # client can still render a minimal reply quote / fetch it.
                    reply_to = {"id": parent_id}
            out.append({
                "id": r.get("id"),
                "speaker_id": r.get("speaker_id"),
                "display_name": r.get("speaker"),
                "is_user": bool(r.get("is_user")),
                "text": r.get("message") or "",
                "timestamp": r.get("timestamp") or "",
                "reactions": r.get("reactions") or [],
                "reply_to": reply_to,
                "thread_root": r.get("thread_root"),
                # Images are not modeled in the conversations table — placeholder
                # so the client shape is stable when image support lands.
                "images": [],
            })
        return out

    from src.platform.community_ctx import run_in_community
    return run_in_community(community_id, _query)


# ── reactions / threads — community-scoped sync helpers ────────────────

def _message_in_channel(community_id: str, message_id: int, channel_id: str) -> bool:
    """True iff ``message_id`` exists AND belongs to ``channel_id`` (cross-channel
    reaction rejection — a target message must live in the channel the actor is
    reacting from). Scopes the community for the lookup."""
    def _check() -> bool:
        from src import db
        try:
            conn = db.get_conn()
            try:
                row = conn.execute(
                    "SELECT channel FROM conversations WHERE id=?", (message_id,)
                ).fetchone()
            finally:
                conn.close()
            return bool(row) and row["channel"] == channel_id
        except Exception:
            return False
    from src.platform.community_ctx import run_in_community
    try:
        return run_in_community(community_id, _check)
    except Exception:
        return False


def _apply_reaction(
    community_id: str, *, message_id: int, actor_id: str, emoji: str, removed: bool,
) -> Optional[dict]:
    """Add/remove a reaction (community-scoped) and return a result dict
    ``{count, changed}`` where ``count`` is the post-mutation total for ``emoji``
    on ``message_id`` and ``changed`` flags a REAL insert (add) so the caller
    fires the relational signal at most once. Returns None on failure.

    Add uses ``store.add_reaction`` (returns True only on a real insert — already
    idempotent via UNIQUE). Remove is unconditional toggle-off. On a real add we
    fire ``memory.record_reaction_signal`` ONCE (dup-guarded in the kernel too).
    """
    def _do() -> dict:
        from src import db
        changed = False
        if removed:
            db.remove_reaction(message_id, actor_id, emoji)
        else:
            changed = db.add_reaction(message_id, actor_id, emoji)
            if changed:
                # Relational interpretation lives in the kernel — the platform
                # only delivers the event. Resolve the agent whose message was
                # reacted to (the message speaker) so the signal targets the
                # right relationship. Fire ONCE (on the real-insert path).
                try:
                    conn = db.get_conn()
                    try:
                        row = conn.execute(
                            "SELECT speaker FROM conversations WHERE id=?",
                            (message_id,),
                        ).fetchone()
                    finally:
                        conn.close()
                    target_agent = row["speaker"] if row else None
                except Exception:
                    target_agent = None
                if target_agent and target_agent != actor_id:
                    try:
                        from glimi import memory
                        memory.record_reaction_signal(target_agent, actor_id, emoji)
                    except Exception:
                        pass
        # Post-mutation count for this emoji on this message.
        try:
            reacts = db.get_reactions(message_id)
            count = sum(1 for r in reacts if r.get("emoji") == emoji)
        except Exception:
            count = 0
        return {"count": count, "changed": changed}

    from src.platform.community_ctx import run_in_community
    try:
        return run_in_community(community_id, _do)
    except Exception:
        return None


def _resolve_actor_name(community_id: str, actor_id: str) -> str:
    """Display name for a reaction actor (owner or agent). Community-scoped."""
    def _name() -> str:
        try:
            from src.core import profile as _profile
            if actor_id == _profile.get_user_id():
                return _profile.get_user_name() or actor_id
            return _profile.get_agent_display_name(actor_id) or actor_id
        except Exception:
            return actor_id
    from src.platform.community_ctx import run_in_community
    try:
        return run_in_community(community_id, _name)
    except Exception:
        return actor_id


def _fetch_thread(community_id: str, root_id: int, limit: int = 50) -> list[dict]:
    """The thread (root + replies) for ``root_id``, display-ready, id ASC.

    Resolves each row's speaker to a display name + ``is_user`` flag (the raw
    ``get_thread`` returns kernel speaker ids), and carries ``reactions`` already
    folded in by the store. Tolerates a missing/trashed root (returns []).
    """
    def _query() -> list[dict]:
        from src import db
        try:
            rows = db.get_thread(root_id, limit=limit)
        except Exception:
            return []
        if not rows:
            return []
        # Resolve display names + user flag (mirror monitor.get_recent_messages).
        agent_names: dict = {}
        user_ids: set = set()
        try:
            for a in db.list_agents():
                if a.get("id"):
                    agent_names[a["id"]] = a.get("name") or a["id"]
        except Exception:
            agent_names = {}
        try:
            for u in db.list_users():
                if u.get("id"):
                    user_ids.add(u["id"])
        except Exception:
            user_ids = set()
        out: list[dict] = []
        for r in rows:
            sid = r.get("speaker")
            is_user = sid in user_ids
            who = agent_names.get(sid)
            if not who and is_user:
                try:
                    u = db.get_user(sid)
                    who = (u or {}).get("name") or sid
                except Exception:
                    who = sid
            out.append({
                "id": r.get("id"),
                "speaker_id": sid,
                "display_name": who or sid,
                "is_user": bool(is_user),
                "text": r.get("message") or "",
                "timestamp": r.get("timestamp") or "",
                "reply_to": {"id": r.get("reply_to")} if r.get("reply_to") else None,
                "thread_root": r.get("thread_root"),
                "reactions": r.get("reactions") or [],
            })
        return out

    from src.platform.community_ctx import run_in_community
    try:
        return run_in_community(community_id, _query)
    except Exception:
        return []


async def _run_turn(
    *, community_id: str, channel_id: str, agent_id: str, text: str,
    outbox: WebOutbox, reply_to: Optional[int] = None,
) -> None:
    """Stream one agent turn back over the socket using the agent's CONFIGURED
    backend (config-layering) — NO backend is forced here.

    Provider selection lives in the kernel runtime (``_provider_for``) and is
    driven by ``os.environ``; the community's LLM keys are loaded from its
    ``.env`` inside the community scope (:func:`_load_community_llm_env`) before
    the runtime call. A misconfigured community emits the kernel's placeholder
    text rather than crashing.

    The kernel streaming call is BLOCKING, so it runs in an executor thread and
    bridges its synchronous ``on_message`` callback onto the event loop via an
    asyncio.Queue (the Discord handler pattern). Each emitted line is
    **persisted first** (``db.log_message`` → row id) and then broadcast as a
    'text' frame carrying that id, so the client can anchor reactions / replies
    on the rendered row (persist-then-broadcast).

    Single-owner: the kernel logs the human turn itself under the owner id
    (its ``log_user_message`` flag defaults True), so we leave that default in
    place and do NOT re-log the owner turn. The kernel does NOT persist agent
    replies — we log each emitted line ourselves (inline, per line).

    ``reply_to`` (the parent message id when the human turn was a reply) is NOT
    threaded onto the agent's reply rows — the agent answers the conversation,
    not the specific quoted line; the reply pointer lives on the human turn only.
    """
    from src.core.runtime import runtime
    from src.platform.community_ctx import run_in_community

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()
    gen_err: dict = {}

    def _on_message(msg: str) -> None:
        # Synchronous kernel callback → hop back onto the loop.
        loop.call_soon_threadsafe(queue.put_nowait, msg)

    def _generate():
        # Scope the community inside the worker thread; the kernel reads
        # process-global state guarded by the community lock.
        def _call():
            # Load this community's CONFIGURED backend keys before the runtime
            # call (Phase-1 _apply_community switches DB/caches but NOT the .env).
            _load_community_llm_env()
            return runtime.generate_response_streaming(
                agent_id, channel_id, text, on_message=_on_message,
            )
        try:
            run_in_community(community_id, _call)
        except Exception as e:
            # Captured (not swallowed) — surfaced as a frame after the drain loop
            # so a kernel failure is visible to the client, never a silent hang.
            gen_err["e"] = e
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    # Resolve the outbound speaker inside the community scope.
    speaker = run_in_community(community_id, lambda: _resolve_speaker(agent_id))

    def _agent_emotion() -> Optional[str]:
        try:
            from src import db
            row = db.get_agent(agent_id)
            return (row or {}).get("current_emotion")
        except Exception:
            return None

    def _persist_line(line: str, emotion: Optional[str]) -> Optional[int]:
        """Persist one agent line and return its row id (None on failure).

        The kernel does NOT persist agent replies (only the owner turn) — we log
        each line here so chat history shows both sides (mirrors Discord's
        handlers._process_and_send). ``db.log_message`` has 30s dup-suppression
        and returns the EXISTING row id on a dup, so the frame always carries a
        real, anchorable id even when a line is re-emitted within the window.
        """
        try:
            from src import db
            return db.log_message(channel_id, agent_id, line, emotion=emotion)
        except Exception:
            return None

    # Resolve emotion once inside the community scope (cheap, avoids per-line
    # scope churn). Falls back to None on any failure.
    emotion = run_in_community(community_id, _agent_emotion)

    await outbox.set_typing(channel_id, speaker, True)
    fut = loop.run_in_executor(None, _generate)
    lines: list[str] = []
    timed_out = False
    try:
        while True:
            item = await asyncio.wait_for(queue.get(), timeout=60.0)
            if item is SENTINEL:
                break
            lines.append(item)
            # Persist-then-broadcast: the frame must carry the persisted id so the
            # client can anchor reactions / replies. Persist in an executor thread
            # (blocking sqlite) scoped to the community; a persist failure still
            # broadcasts with id=None so the user is never left hanging.
            try:
                mid = await loop.run_in_executor(
                    None, lambda ln=item: run_in_community(
                        community_id, lambda: _persist_line(ln, emotion)),
                )
            except Exception:
                mid = None
            await outbox.send_text(channel_id, speaker, item, message_id=mid)
    except asyncio.TimeoutError:
        timed_out = True
        await outbox.send_text(channel_id, speaker, "[오류] 응답 시간이 초과되었습니다.")
    finally:
        await outbox.set_typing(channel_id, speaker, False)
        try:
            await fut
        except Exception:
            pass

    # Reply pointer backfill: the kernel logs the human turn itself (under the
    # owner id) WITHOUT a reply_to (it does not know the web reply context). When
    # the human turn was a reply, backfill the pointer onto that just-logged row
    # so the reply survives reload + threads. We do NOT suppress the kernel's
    # human-turn logging (the kernel must own it — source guard keeps the default
    # log flag True) — instead we resolve the row the kernel wrote and set its
    # reply_to (a post-hoc backfill, not a logging override). Validated against the
    # owner id + the exact text within the channel; best-effort, never fatal.
    if reply_to is not None:
        def _backfill_reply() -> None:
            from src import db
            owner_id = _resolve_owner_speaker_id()
            try:
                conn = db.get_conn()
                try:
                    row = conn.execute(
                        "SELECT id FROM conversations "
                        "WHERE channel=? AND speaker=? AND message=? "
                        "ORDER BY id DESC LIMIT 1",
                        (channel_id, owner_id, text),
                    ).fetchone()
                finally:
                    conn.close()
                if row is not None:
                    db.set_reply(row["id"], reply_to)
            except Exception:
                pass
        try:
            await loop.run_in_executor(
                None, lambda: run_in_community(community_id, _backfill_reply))
        except Exception:
            pass

    # No line produced and no timeout → the kernel raised or returned nothing.
    # Surface it as a 'text' frame so the user sees a result and the client is
    # never left blocking on a reply that never comes (was a silent hang).
    if not lines and not timed_out:
        err = gen_err.get("e")
        detail = f" ({type(err).__name__})" if err is not None else ""
        await outbox.send_text(
            channel_id, speaker, f"[오류] 응답을 생성하지 못했어요{detail}.",
        )


@router.get("/community/{cid}/chat/channels")
async def chat_channels(cid: str, request: Request):
    """The owner's user-postable channels (dm-*, group-*) with display metadata.

    Auth-gated (login + per-community access). Internal channels (mgr-*/
    internal-*) are excluded — they are not user-postable.
    """
    _api_user(request, cid)
    try:
        channels = _list_postable_channels(cid)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"community_id": cid, "channels": channels})


@router.get("/community/{cid}/chat/history")
async def chat_history(
    cid: str, request: Request,
    channel: str = "", limit: int = 50,
):
    """Recent messages for a channel, newest-last, display-ready.

    Auth-gated + per-community access. Rejects non-user-postable channels so the
    history surface matches the postable channel list.
    """
    _api_user(request, cid)
    channel = (channel or "").strip()
    if not channel:
        return JSONResponse({"error": "missing channel"}, status_code=400)
    if not is_user_postable(channel):
        return JSONResponse({"error": "channel is not user-postable"}, status_code=400)
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        messages = _channel_history(cid, channel, limit)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"community_id": cid, "channel": channel, "messages": messages})


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

    from src.platform.community_ctx import run_in_community

    try:
        while True:
            frame = await websocket.receive_json()
            ftype = (frame.get("type") or "text").strip()
            channel_id = (frame.get("channel") or "").strip()
            frame_agent = (frame.get("agent") or "").strip()

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

            # All non-text frames (reactions / threads) require a user-postable
            # channel too — the same guard the text path uses.
            if ftype in ("add_reaction", "remove_reaction", "fetch_thread"):
                if not is_user_postable(channel_id):
                    await websocket.send_json({
                        "type": "error", "channel": channel_id,
                        "error": "channel is not user-postable",
                    })
                    continue

            if ftype in ("add_reaction", "remove_reaction"):
                # {type, channel, id(target), emoji}. Auth = is_user_postable
                # (above) + the target must belong to THIS channel (reject
                # cross-channel). Actor = the single owner.
                try:
                    target_id = int(frame.get("id"))
                except (TypeError, ValueError):
                    await websocket.send_json({
                        "type": "error", "channel": channel_id,
                        "error": "missing/invalid message id",
                    })
                    continue
                emoji = (frame.get("emoji") or "").strip()
                if not emoji:
                    await websocket.send_json({
                        "type": "error", "channel": channel_id,
                        "error": "missing emoji",
                    })
                    continue
                if not _message_in_channel(cid, target_id, channel_id):
                    await websocket.send_json({
                        "type": "error", "channel": channel_id,
                        "error": "target message not in channel",
                    })
                    continue
                actor_id = run_in_community(cid, _resolve_owner_speaker_id)
                removed = (ftype == "remove_reaction")
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _apply_reaction(
                        cid, message_id=target_id, actor_id=actor_id,
                        emoji=emoji, removed=removed),
                )
                if result is None:
                    await websocket.send_json({
                        "type": "error", "channel": channel_id,
                        "error": "reaction failed",
                    })
                    continue
                actor_name = _resolve_actor_name(cid, actor_id)
                await outbox.emit_reaction(
                    channel_id, message_id=target_id, actor_id=actor_id,
                    actor_name=actor_name, emoji=emoji,
                    count=int(result.get("count") or 0), removed=removed,
                )
                continue

            if ftype == "fetch_thread":
                # {type, channel, root} → a 'thread' frame (root + replies) back
                # to THIS socket only (not a broadcast).
                try:
                    root_id = int(frame.get("root"))
                except (TypeError, ValueError):
                    await websocket.send_json({
                        "type": "error", "channel": channel_id,
                        "error": "missing/invalid thread root",
                    })
                    continue
                msgs = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _fetch_thread(cid, root_id),
                )
                await websocket.send_json({
                    "type": "thread", "channel": channel_id,
                    "root": root_id, "messages": msgs,
                })
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

            # Optional reply pointer (the parent message id this turn replies to).
            reply_to = None
            if frame.get("reply_to") is not None:
                try:
                    reply_to = int(frame.get("reply_to"))
                except (TypeError, ValueError):
                    reply_to = None
                # A reply target must belong to this channel (cross-channel reject
                # — silently drop the pointer rather than fail the whole turn).
                if reply_to is not None and not _message_in_channel(cid, reply_to, channel_id):
                    reply_to = None

            # Resolve which agent answers (DM → channel's agent; group → frame's
            # agent, v1 single-agent; never crash). channel_kind falls UNKNOWN →
            # 'group' → postable, so validate the agent exists before spawning a
            # turn for a non-existent agent.
            agent_id = _resolve_responding_agent(channel_id, frame_agent)
            if not _agent_exists(cid, agent_id):
                await websocket.send_json({
                    "type": "error",
                    "channel": channel_id,
                    "error": f"unknown agent: {agent_id}",
                })
                continue

            await _run_turn(
                community_id=cid, channel_id=channel_id,
                agent_id=agent_id, text=text, outbox=outbox,
                reply_to=reply_to,
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
