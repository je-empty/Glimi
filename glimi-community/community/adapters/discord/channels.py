# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""DiscordChannelAdapter — the Discord implementation of
:class:`community.core.channel_adapter.ChannelAdapter`.

Wraps the existing ``community.bot.core`` ops VERBATIM (webhooks, ``discord.utils.get``,
category layout) so the factory's Discord branch resolves and Discord keeps running
through the same port during the migration. This is the SANCTIONED home for Discord
channel-op code — ``import discord`` is allowed HERE (the adapter boundary) and is
deferred to call time so that:
  - the web process never imports discord (the module is import-light), and
  - a checkout WITHOUT ``discord`` installed can still ``py_compile`` this file
    (the import only fires when a Discord transport actually calls an op).

All guild resolution goes through ``bot.core.get_target_guild`` (honors
``DISCORD_GUILD_ID``). Channel lookups use ``discord.utils.get(guild.text_channels,
name=...)``; creation goes through ``bot.core`` /``core.sync.ensure_unique_channel``
(the at-most-1 guard). NOTHING in here is exercised in the discord-free CI — it is
verified by ``py_compile`` only (per the Phase-2 plan).
"""
from __future__ import annotations

from typing import Optional

from community.core.channel_adapter import ChannelRef, HistoryMsg


class DiscordChannelAdapter:
    """Structurally satisfies :class:`community.core.channel_adapter.ChannelAdapter`.

    Stateless — resolves the live guild on every op via ``bot.core.get_target_guild``
    so a reconnect (new guild object) is picked up without re-instantiation.
    """

    def _guild(self):
        """The live target guild, or None if the bot is not connected."""
        from community.bot import core as _core
        return _core.get_target_guild()

    def _find(self, guild, channel_name: str):
        """``discord.utils.get(guild.text_channels, name=normalized)`` — the same
        normalized lookup ``core.sync.ensure_unique_channel`` uses."""
        import discord
        from community.core.channels import normalize_channel_name
        if guild is None:
            return None
        normalized = normalize_channel_name(channel_name)
        ch = discord.utils.get(guild.text_channels, name=normalized)
        if ch is None and normalized != channel_name:
            ch = discord.utils.get(guild.text_channels, name=channel_name)
        return ch

    # ── messaging ───────────────────────────────────────────────

    async def send_as_agent(self, channel_name: str, agent_id: str, text: str,
                            *, paced: bool = True) -> None:
        from community.bot import core as _core
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return
        await _core.send_as_agent(ch, agent_id, text, paced=paced)

    async def send_as_owner(self, channel_name: str, text: str) -> None:
        # Owner messages go through a plain (avatar-less) webhook — mirror
        # bot.core._get_plain_webhook + send. The web adapter logs as owner; the
        # Discord adapter posts to the channel.
        from community.bot import core as _core
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return
        webhook = await _core._get_plain_webhook(ch)
        await webhook.send(content=text)

    async def send_image_as_agent(self, channel_name: str, agent_id: str,
                                  image_path: str, caption: str = "") -> None:
        from community.bot import core as _core
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return
        await _core.send_image_as_agent(ch, agent_id, image_path, caption)

    async def refresh_agent_avatar(self, agent_id: str, *,
                                   channels: Optional[list] = None) -> int:
        """Push the agent's profile image onto its per-channel webhooks (verbatim
        ``bot.core.update_agent_webhook_profile_image`` loop). Returns the count of
        channels updated."""
        from community.bot import core as _core
        guild = self._guild()
        if guild is None:
            return 0
        updated = 0
        for ch in guild.text_channels:
            try:
                if await _core.update_agent_webhook_profile_image(ch, agent_id):
                    updated += 1
            except Exception:
                pass
        return updated

    # ── lifecycle ───────────────────────────────────────────────

    async def ensure_channel(self, channel_name: str, *,
                             participants: Optional[list] = None) -> ChannelRef:
        from community.bot import core as _core
        from community.core.sync import ensure_unique_channel
        guild = self._guild()
        if guild is None:
            return ChannelRef(name=channel_name, id="", created=False)
        cat_name = _core._get_category_for_channel(channel_name)
        category = await _core._ensure_category(guild, cat_name)
        ch, created = await ensure_unique_channel(guild, channel_name, category=category)
        # Keep the DB participant registry in sync (Discord side mirrors to DB).
        if participants is not None:
            try:
                from community import db
                db.set_channel_participants(ch.name, participants)
            except Exception:
                pass
        return ChannelRef(name=ch.name, id=str(ch.id), created=created)

    async def find_channel(self, channel_name: str) -> Optional[ChannelRef]:
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return None
        return ChannelRef(name=ch.name, id=str(ch.id), created=False)

    async def channel_exists(self, channel_name: str) -> bool:
        return self._find(self._guild(), channel_name) is not None

    async def delete_channel(self, channel_name: str, *, reason: str = "") -> bool:
        from community import db
        # Deletion protection mirrors the web side (dm-/mgr- are owner core lines).
        if db._is_protected_channel(channel_name):
            return False
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return False
        await ch.delete(reason=reason or None)
        try:
            db.delete_channel(channel_name)
        except Exception:
            pass
        return True

    async def rename_channel(self, old_name: str, new_name: str) -> bool:
        from community import db
        ch = self._find(self._guild(), old_name)
        if ch is None:
            return False
        from community.core.channels import normalize_channel_name
        await ch.edit(name=normalize_channel_name(new_name))
        try:
            db.rename_channel(old_name, ch.name)
        except Exception:
            pass
        return True

    async def set_topic(self, channel_name: str, topic: str) -> bool:
        from community import db
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return False
        await ch.edit(topic=topic)
        try:
            db.set_channel_topic(channel_name, topic)
        except Exception:
            pass
        return True

    # ── listing / introspection ─────────────────────────────────

    async def list_channels(self, *, fresh: bool = False) -> list[ChannelRef]:
        guild = self._guild()
        if guild is None:
            return []
        return [ChannelRef(name=ch.name, id=str(ch.id), created=False)
                for ch in guild.text_channels]

    # ── history / moderation ────────────────────────────────────

    async def get_history(self, channel_name: str, limit: int = 30) -> list[HistoryMsg]:
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return []
        out: list[HistoryMsg] = []
        async for msg in ch.history(limit=limit):
            out.append(HistoryMsg(
                author=getattr(msg.author, "name", "") or "",
                text=msg.content or "",
                created_at=msg.created_at.isoformat() if msg.created_at else "",
            ))
        out.reverse()  # discord history is newest-first; return ASC
        return out

    async def purge_messages(self, channel_name: str, limit: int) -> int:
        ch = self._find(self._guild(), channel_name)
        if ch is None:
            return 0
        deleted = await ch.purge(limit=limit)
        return len(deleted)

    # ── layout (discord categories) ─────────────────────────────

    async def reorder_categories(self) -> None:
        """Reorder the glimi categories to ``CATEGORY_ORDER`` (verbatim sync logic)."""
        import discord
        from community.core.channels import CATEGORY_ORDER
        guild = self._guild()
        if guild is None:
            return
        for i, cat_name in enumerate(CATEGORY_ORDER):
            cat = discord.utils.get(guild.categories, name=cat_name)
            if cat is not None:
                try:
                    await cat.edit(position=i)
                except Exception:
                    pass


_ADAPTER: Optional[DiscordChannelAdapter] = None


def get_discord_adapter() -> DiscordChannelAdapter:
    """Process-singleton Discord adapter (stateless — guild resolved per op)."""
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = DiscordChannelAdapter()
    return _ADAPTER
