# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Discord transport adapter — the ``community.core.channel_adapter.ChannelAdapter``
implementation wrapping the existing ``community.bot.core`` ops (webhooks,
``discord.utils.get``, category layout).

This is the SANCTIONED home for Discord channel-op code: ``import discord`` IS
allowed in this subpackage (it is the adapter boundary), but NOWHERE else under
``community.core`` / ``community.adapters.web``. The factory
``community.core.channel_adapter.get_channel_adapter()`` resolves
:func:`~community.adapters.discord.channels.get_discord_adapter` when
``GLIMI_TRANSPORT`` is not ``web``.
"""
