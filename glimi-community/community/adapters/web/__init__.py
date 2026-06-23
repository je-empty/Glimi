# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Web transport adapter — the ``community.core.channel_adapter.ChannelAdapter``
implementation backed by ``community.db`` + ``community.core.monitor`` +
``community.platform.chat_hub`` (no Discord).

``import discord`` is forbidden here (CLAUDE.md decoupling). The factory
``community.core.channel_adapter.get_channel_adapter()`` resolves
:class:`~community.adapters.web.channels.WebChannelAdapter` when
``GLIMI_TRANSPORT=web``.
"""
