# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Supervisor registrar — transport-neutral (was ``community/bot/supervisors.py``).

Registers the system supervisors + runs the initial pool sync, and provides the
idle-nudge entrypoints. The old ``bot/supervisors.py`` resolved a live Discord
``guild`` (``get_target_guild``) and ticked ``pool.tick(guild=…)``; this version
uses the :class:`community.core.channel_adapter.ChannelAdapter` from the factory
so it works for BOTH transports (web runtime + the discord shim call it).

``import discord`` is never present here (CLAUDE.md decoupling) — the adapter is
the only outbound seam.
"""
from __future__ import annotations

import asyncio

from community import db, log_writer
from community.core.channels import MGR_CHANNEL, CREATOR_CHANNEL
# Importing the scene module registers the tutorial scene in the registry (side
# effect) so pool.sync() can discover its scene-scoped supervisor.
from community.scenes.tutorial import scene as _tutorial_scene  # noqa: F401


_notify_idle_tasks: dict[str, asyncio.Task] = {}  # 채널별 대기 태스크 (중복 방지)


async def _run_checks() -> None:
    """pool.tick() 위임 — 어댑터 경유 (transport-neutral). guild 없이 동작."""
    from community.core.channel_adapter import get_channel_adapter
    from community.supervisors.base import pool
    await pool.tick(channels=get_channel_adapter())


async def notify_idle(channel_name: str) -> None:
    """에이전트 응답 완료 후 호출 — 일정 시간 후 유저 응답 없으면 pool tick 실행."""
    relevant = (
        channel_name in (MGR_CHANNEL, CREATOR_CHANNEL)
        or channel_name.startswith("internal-")
    )
    if not relevant:
        return

    prev = _notify_idle_tasks.get(channel_name)
    if prev and not prev.done():
        prev.cancel()

    async def _delayed_check():
        await asyncio.sleep(15)  # 15초 대기 — 유저 응답 기다림
        recent = db.get_recent_messages(channel_name, limit=1)
        if recent:
            from community.core.profile import get_user_id
            last_speaker = recent[-1]["speaker"]
            if last_speaker != get_user_id():
                await _run_checks()

    _notify_idle_tasks[channel_name] = asyncio.create_task(_delayed_check())


def start_supervisors() -> None:
    """런타임 ready 시 호출: system supervisors 등록 + 최초 sync."""
    from community.supervisors.base import pool
    pool.register_system_supervisors()

    # 초기 scene/channel sync는 별도 태스크로 (지금 시점엔 이벤트 루프 안).
    async def _initial_sync():
        try:
            await pool.sync()
            log_writer.system(
                f"[supervisor] pool 초기화: "
                f"{', '.join(s.id for s in pool.all())}"
            )
        except Exception as e:
            log_writer.system(f"[supervisor] 초기 sync 오류: {e}")

    try:
        asyncio.get_event_loop().create_task(_initial_sync())
    except RuntimeError:
        # 이벤트 루프 없으면 무시 (런타임 아직 안 뜸).
        pass
