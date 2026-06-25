# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
채널별 async 잠금 — transport 중립.

모든 writer(WS _run_turn, supervisor _inject_and_send, web greeting)가 공유하는
단일 mutex. 코어에 두어 어떤 어댑터에서도 같은 잠금을 공유한다.

키는 (community_id, channel_name) — 한 프로세스가 N 커뮤니티를 서빙해도 채널 잠금이
커뮤니티 경계를 넘지 않도록. (web_runtime 핀드 프로세스에선 1커뮤니티라 belt-and-suspenders.)
"""
import asyncio

_CHANNEL_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


def get_channel_lock(community_id: str, channel_name: str) -> asyncio.Lock:
    key = (community_id, channel_name)
    lock = _CHANNEL_LOCKS.get(key)
    if lock is None:
        lock = _CHANNEL_LOCKS[key] = asyncio.Lock()
    return lock
