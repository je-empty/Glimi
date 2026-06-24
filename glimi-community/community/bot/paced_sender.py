# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""DEPRECATED 위치 — 페이싱 로직은 community.core.paced_sender 로 이동(discord-free).

이 shim 은 discord.TextChannel 객체를 받아 채널명 문자열로 변환해 core PacedSender 로
위임 (Discord 어댑터 전용). 신규 코드(웹/코어)는 core 의 ``paced`` 를 채널명으로 직접 사용.
"""
from __future__ import annotations

from community.core.paced_sender import (  # noqa: F401
    PacedSender as _CorePacedSender,
    MIN_TYPING_DELAY,
    PER_CHAR_DELAY,
    MAX_TYPING_DELAY,
    INTRA_AGENT_GAP,
    AGENT_SWITCH_LEAD,
    WORKER_IDLE_TIMEOUT,
)


def _ch_name(channel) -> str:
    if not channel:
        return ""
    return getattr(channel, "name", None) or str(getattr(channel, "id", "?"))


class PacedSender(_CorePacedSender):
    """discord 채널 객체 → 채널명 변환 후 core 위임 (인자 형태 하위호환)."""

    async def enqueue(self, channel, agent_id, content, send_fn):  # type: ignore[override]
        return await super().enqueue(_ch_name(channel), agent_id, content, send_fn)

    async def flush(self, channel):  # type: ignore[override]
        return await super().flush(_ch_name(channel))


# 싱글턴 (기존 community.bot.core import 호환)
paced = PacedSender()
