# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
ChannelAdapter — 플랫폼 중립 "출구" 포트 (Discord / 웹챗 공용).

코어 온보딩 두뇌(runtime.generate_response*, 프롬프트, 씬 페이즈, 친구생성)는
이 포트만 통해 메시지를 보내고 채널을 만든다 → Discord 타입이 코어로 새지 않음.

구현:
  - DiscordChannelAdapter (community/adapters/discord/channels.py) : 기존 bot/core 함수 래핑
  - WebChannelAdapter      (community/adapters/web/channels.py)     : db + chat_hub

`import discord` 절대 금지 (CLAUDE.md decoupling). 값 객체도 여기 둠.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChannelRef:
    """채널 한 개에 대한 중립 참조. discord: id=str(channel.id); web: id=채널명."""
    name: str
    id: str
    created: bool = False


@dataclass(frozen=True)
class HistoryMsg:
    author: str
    text: str
    created_at: str


@runtime_checkable
class ChannelAdapter(Protocol):
    # ── messaging ───────────────────────────────────────────────
    async def send_as_agent(self, channel_name: str, agent_id: str, text: str, *, paced: bool = True) -> None: ...
    async def send_as_owner(self, channel_name: str, text: str) -> None: ...
    async def send_image_as_agent(self, channel_name: str, agent_id: str, image_path: str, caption: str = "") -> None: ...
    async def refresh_agent_avatar(self, agent_id: str, *, channels: Optional[list[str]] = None) -> int: ...
    # ── lifecycle ───────────────────────────────────────────────
    async def ensure_channel(self, channel_name: str, *, participants: Optional[list[str]] = None) -> ChannelRef: ...
    async def find_channel(self, channel_name: str) -> Optional[ChannelRef]: ...
    async def delete_channel(self, channel_name: str, *, reason: str = "") -> bool: ...
    async def rename_channel(self, old_name: str, new_name: str) -> bool: ...
    async def set_topic(self, channel_name: str, topic: str) -> bool: ...
    # ── listing / introspection ─────────────────────────────────
    async def list_channels(self, *, fresh: bool = False) -> list[ChannelRef]: ...
    async def channel_exists(self, channel_name: str) -> bool: ...
    # ── history / moderation ────────────────────────────────────
    async def get_history(self, channel_name: str, limit: int = 30) -> list[HistoryMsg]: ...
    async def purge_messages(self, channel_name: str, limit: int) -> int: ...
    # ── layout (discord categories; web no-op) ──────────────────
    async def reorder_categories(self) -> None: ...


def get_channel_adapter() -> "ChannelAdapter":
    """팩토리 — 항상 WebChannelAdapter (웹이 유일 transport).

    지연 import 로 플랫폼 모듈 순환을 피한다.
    """
    from community.adapters.web.channels import WebChannelAdapter
    from community.community import get_community_id
    return WebChannelAdapter(get_community_id())
