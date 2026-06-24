# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""WebChannelAdapter — the web implementation of
:class:`community.core.channel_adapter.ChannelAdapter`.

Backed by ``community.db`` (channel registry + message log), ``community.core.monitor``
(read API), ``community.platform.chat_hub`` (broadcast), and ``community.core.paced_sender``
(human-paced delivery). NO Discord imports/types (CLAUDE.md decoupling).

Frame contract — IDENTICAL to ``community.platform.routers.chat.WebOutbox``:
  - text:  ``{type:'text',  channel, id, agent_id, speaker, text}``
  - image: ``{type:'image', channel, id, agent_id, speaker, url, caption}``
the JS chat client renders both shapes; an agent line sent through this adapter
must be indistinguishable from one a WS turn emitted.

CRITICAL (per the Phase-2 plan): this adapter calls ``db.*`` DIRECTLY and never
``run_in_community`` — the community scope is the caller's responsibility (the
adapter is already constructed inside the active community, and ``db`` resolves
the path from the active community). Re-scoping here would nest locks.
"""
from __future__ import annotations

from typing import Optional

from community.core.channel_adapter import ChannelRef, HistoryMsg


class WebChannelAdapter:
    """Structurally satisfies :class:`community.core.channel_adapter.ChannelAdapter`
    (``runtime_checkable`` Protocol → ``isinstance`` is True).

    ``community_id`` is the broadcast key for :mod:`chat_hub` — it must match the
    ``cid`` the WS connections registered under so a supervisor-driven send reaches
    the owner's open socket. DB ops resolve the path from the active community
    scope (the caller sets it), so ``community_id`` is used ONLY for broadcasts.
    """

    def __init__(self, community_id: str):
        self.community_id = community_id

    # ── internal helpers ────────────────────────────────────────

    def _speaker(self, agent_id: str) -> tuple[str, str]:
        """``(agent_id, display_name)`` for the outbound frame's ``agent_id`` /
        ``speaker`` fields. Mirrors ``chat._resolve_speaker`` (best-effort name)."""
        display = agent_id
        try:
            from community.core import profile as _profile
            display = _profile.get_agent_display_name(agent_id) or agent_id
        except Exception:
            pass
        return agent_id, display

    async def _broadcast(self, channel_name: str, frame: dict) -> str:
        """Broadcast a frame to every socket on ``(community_id, channel_name)``.
        Mirrors ``WebOutbox._broadcast`` — sets ``channel`` and returns the id."""
        from community.platform import chat_hub
        frame.setdefault("channel", channel_name)
        await chat_hub.broadcast(self.community_id, channel_name, frame)
        return str(frame.get("id") or "")

    # ── messaging ───────────────────────────────────────────────

    async def send_as_agent(self, channel_name: str, agent_id: str, text: str,
                            *, paced: bool = True) -> None:
        """Persist one agent line + broadcast a 'text' frame (persist-then-broadcast).

        Drops meaningless lines ('...' etc.) to mirror the Discord ``send_as_agent``
        leak guard. ``paced=True`` routes the broadcast through
        :class:`community.core.paced_sender.PacedSender` so multi-line / multi-agent
        bursts arrive at human speed; the persisted id is resolved BEFORE pacing so
        the frame always carries a real, anchorable id.
        """
        stripped = (text or "").strip()
        if not stripped or stripped in {".", "..", "...", "....", "…", "..…", "....."}:
            return

        from community import db
        agent_id_resolved, display = self._speaker(agent_id)

        emotion = None
        try:
            row = db.get_agent(agent_id)
            emotion = (row or {}).get("current_emotion")
        except Exception:
            emotion = None

        try:
            mid = db.log_message(channel_name, agent_id, text, emotion=emotion)
        except Exception:
            mid = None

        frame = {
            "type": "text",
            "id": mid,
            "agent_id": agent_id_resolved,
            "speaker": display,
            "text": text,
        }

        async def _send() -> None:
            await self._broadcast(channel_name, frame)

        if paced:
            from community.core.paced_sender import paced as _paced
            await _paced.enqueue(channel_name, agent_id, text, _send)
        else:
            await _send()

    async def send_as_owner(self, channel_name: str, text: str) -> None:
        """Persist + broadcast a line AS THE OWNER (the human turn).

        Used by flows that inject an owner message web-side. Persisted under the
        owner speaker id; broadcast as a 'text' frame with the owner's display
        name so the client renders it on the user side.
        """
        stripped = (text or "").strip()
        if not stripped:
            return
        from community import db
        owner_id, owner_name = "owner", "나"
        try:
            from community.core import profile as _profile
            owner_id = _profile.get_user_id() or "owner"
            owner_name = _profile.get_user_name() or owner_id
        except Exception:
            pass
        try:
            mid = db.log_message(channel_name, owner_id, text)
        except Exception:
            mid = None
        await self._broadcast(channel_name, {
            "type": "text",
            "id": mid,
            "agent_id": owner_id,
            "speaker": owner_name,
            "text": text,
        })

    async def send_image_as_agent(self, channel_name: str, agent_id: str,
                                  image_path: str, caption: str = "") -> None:
        """Persist the caption as an agent line + broadcast an 'image' frame.

        The web has no file upload to a CDN — the agent's image (imagegen reveal)
        is served live by ``/api/avatar`` keyed on the agent id (the reveal updates
        the agent's ``profile_image_filename``). So the frame ``url`` points at that
        live avatar route, matching ``WebOutbox.send_image`` shape exactly.
        ``image_path`` is accepted for signature parity but not embedded (the web
        does not expose arbitrary filesystem paths).
        """
        from community import db
        agent_id_resolved, display = self._speaker(agent_id)
        # Persist the caption (if any) as the agent's line so history shows the
        # reveal moment; the image itself rides the live avatar URL.
        mid = None
        if (caption or "").strip():
            try:
                mid = db.log_message(channel_name, agent_id, caption)
            except Exception:
                mid = None
        url = f"/api/avatar?community={self.community_id}&id={agent_id_resolved}"
        await self._broadcast(channel_name, {
            "type": "image",
            "id": mid,
            "agent_id": agent_id_resolved,
            "speaker": display,
            "url": url,
            "caption": caption,
        })

    async def refresh_agent_avatar(self, agent_id: str, *,
                                   channels: Optional[list] = None) -> int:
        """NO-OP on web → returns 0.

        Discord pushes the avatar onto per-channel webhooks; the web serves the
        agent avatar live from ``/api/avatar`` (no per-channel push needed). The
        return is the count of channels updated — always 0 here.
        """
        return 0

    # ── lifecycle ───────────────────────────────────────────────

    async def ensure_channel(self, channel_name: str, *,
                             participants: Optional[list] = None) -> ChannelRef:
        """Ensure the channel exists (status-preserving) and return a ``ChannelRef``.

        ``created`` reflects whether this call inserted the row (the channel did not
        exist before). Backed by ``db.ensure_channel`` — never resets a running
        channel's status/current_turn.
        """
        from community import db
        existed = await self.channel_exists(channel_name)
        db.ensure_channel(channel_name, participants)
        return ChannelRef(name=channel_name, id=channel_name, created=not existed)

    async def find_channel(self, channel_name: str) -> Optional[ChannelRef]:
        """Return a ``ChannelRef`` if the channel is registered, else None."""
        if await self.channel_exists(channel_name):
            return ChannelRef(name=channel_name, id=channel_name, created=False)
        return None

    async def channel_exists(self, channel_name: str) -> bool:
        """True iff a ``channels`` row exists for ``channel_name``."""
        from community import db
        try:
            conn = db.get_conn()
            try:
                row = conn.execute(
                    "SELECT 1 FROM channels WHERE channel = ?", (channel_name,)
                ).fetchone()
            finally:
                conn.close()
            return row is not None
        except Exception:
            return False

    async def delete_channel(self, channel_name: str, *, reason: str = "") -> bool:
        """Delete the channel (data + registry row). Returns False for a protected
        ``dm-``/``mgr-`` channel (per ``db.delete_channel``)."""
        from community import db
        try:
            return db.delete_channel(channel_name)
        except Exception:
            return False

    async def rename_channel(self, old_name: str, new_name: str) -> bool:
        """Rename across the registry + every name-keyed table (single txn).
        Returns True on success, False on failure."""
        from community import db
        try:
            db.rename_channel(old_name, new_name)
            return True
        except Exception:
            return False

    async def set_topic(self, channel_name: str, topic: str) -> bool:
        """Set the channel topic (``channels.topic``). Returns True on success."""
        from community import db
        try:
            db.set_channel_topic(channel_name, topic)
            return True
        except Exception:
            return False

    # ── listing / introspection ─────────────────────────────────

    async def list_channels(self, *, fresh: bool = False) -> list[ChannelRef]:
        """All registered channels as ``ChannelRef`` (``monitor.get_channels``)."""
        from community.core import monitor
        try:
            chans = monitor.get_channels()
        except Exception:
            chans = []
        out: list[ChannelRef] = []
        for ch in chans:
            name = ch.get("name") or ""
            if name:
                out.append(ChannelRef(name=name, id=name, created=False))
        return out

    # ── history / moderation ────────────────────────────────────

    async def get_history(self, channel_name: str, limit: int = 30) -> list[HistoryMsg]:
        """Recent messages as ``HistoryMsg`` (author/text/created_at), ASC."""
        from community.core import monitor
        try:
            rows = monitor.get_recent_messages(limit=limit, channel=channel_name)
        except Exception:
            rows = []
        out: list[HistoryMsg] = []
        for r in rows:
            out.append(HistoryMsg(
                author=r.get("speaker") or "",
                text=r.get("message") or "",
                created_at=r.get("timestamp") or "",
            ))
        return out

    async def purge_messages(self, channel_name: str, limit: int) -> int:
        """Delete up to ``limit`` most-recent messages from the channel.

        Returns the number deleted. Used by moderation tools; web has no Discord
        bulk-delete API, so it deletes rows directly from ``conversations``.
        """
        from community import db
        try:
            conn = db.get_conn()
            try:
                rows = conn.execute(
                    "SELECT id FROM conversations WHERE channel = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (channel_name, max(0, int(limit))),
                ).fetchall()
                ids = [r["id"] for r in rows]
                if ids:
                    qmarks = ",".join("?" for _ in ids)
                    conn.execute(
                        f"DELETE FROM conversations WHERE id IN ({qmarks})", ids
                    )
                    conn.commit()
                return len(ids)
            finally:
                conn.close()
        except Exception:
            return 0

    # ── layout (discord categories; web no-op) ──────────────────

    async def reorder_categories(self) -> None:
        """NO-OP — the web has no Discord category layout."""
        return None
