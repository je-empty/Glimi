# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
PacedSender — 에이전트 메시지가 실제 사람 타이핑처럼 페이스 조절되어 나가도록.

문제: LLM 이 응답 여러 줄을 빠르게 쏟아내고, 그룹 채팅에서 여러 에이전트가 동시에
스트리밍하면 전송이 뭉텅이로 쌓여 우다다다 한꺼번에 보임.
해결: 채널별 단일 FIFO 큐 + 워커. 전송 전후로 길이 비례 딜레이 + gap. 에이전트 전환 시
리드인 딜레이.

플랫폼 중립 (discord-free): 채널은 **이름 문자열**로만 식별, 실제 전송은 주입된 ``send_fn``.
어댑터가 자기 채널 객체를 이름 문자열로 래핑해 주입하면 된다.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, Optional

log = logging.getLogger("community.paced_sender")

# 타이밍 파라미터 — 실제 대화 관찰해서 조정
MIN_TYPING_DELAY = 0.15
PER_CHAR_DELAY = 0.015   # 글자당 약 15ms
MAX_TYPING_DELAY = 1.5   # 긴 메시지 상한

INTRA_AGENT_GAP = (0.15, 0.35)     # 같은 에이전트 연쇄 메시지 사이
AGENT_SWITCH_LEAD = (0.4, 1.0)     # 에이전트 전환 시 앞에 붙는 '생각하는' 시간
WORKER_IDLE_TIMEOUT = 120          # 2분 idle면 워커 종료


class PacedSender:
    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._last_agent: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        channel_name: str,
        agent_id: str,
        content: str,
        send_fn: Callable[[], Awaitable[None]],
    ):
        """메시지를 채널 큐에 enqueue. 워커는 필요 시 자동 시작."""
        if not channel_name:
            # 채널명 없으면 바로 전송 (fallback)
            try:
                await send_fn()
            except Exception as e:
                log.warning("[PacedSender] direct send fail: %s", e)
            return
        q = await self._ensure_worker(channel_name)
        await q.put((agent_id, content, send_fn))

    async def _ensure_worker(self, ch_name: str) -> asyncio.Queue:
        async with self._lock:
            q = self._queues.get(ch_name)
            if q is None:
                q = asyncio.Queue()
                self._queues[ch_name] = q
                self._workers[ch_name] = asyncio.create_task(
                    self._worker(ch_name),
                    name=f"paced-sender:{ch_name}",
                )
            return q

    async def _worker(self, ch_name: str):
        q = self._queues[ch_name]
        last_agent: Optional[str] = self._last_agent.get(ch_name)

        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=WORKER_IDLE_TIMEOUT)
            except asyncio.TimeoutError:
                # idle → 워커 종료 + 상태 정리
                async with self._lock:
                    self._queues.pop(ch_name, None)
                    self._workers.pop(ch_name, None)
                    if last_agent:
                        self._last_agent[ch_name] = last_agent
                return

            agent_id, content, send_fn = item
            length = len(content or "")

            # 에이전트 전환 시 리드인 (다른 사람이 타이핑 시작하는 느낌)
            if last_agent and last_agent != agent_id:
                await asyncio.sleep(random.uniform(*AGENT_SWITCH_LEAD))

            # 타이핑 딜레이 (길이 비례)
            typing_delay = min(MAX_TYPING_DELAY, MIN_TYPING_DELAY + length * PER_CHAR_DELAY)
            await asyncio.sleep(typing_delay)

            # 실제 전송
            try:
                await send_fn()
            except Exception as e:
                log.warning("[PacedSender] send fail #%s: %s", ch_name, e)

            # 같은 에이전트 연쇄 간 gap
            await asyncio.sleep(random.uniform(*INTRA_AGENT_GAP))

            last_agent = agent_id
            self._last_agent[ch_name] = agent_id

    async def flush(self, channel_name: str) -> None:
        """해당 채널 큐가 완전히 비워질 때까지 대기 (최대 30초)."""
        if not channel_name:
            return
        q = self._queues.get(channel_name)
        if q is None:
            return
        for _ in range(300):  # 100ms * 300 = 30s 상한
            if q.empty():
                return
            await asyncio.sleep(0.1)


# 싱글턴 (웹 런타임이 직접 사용)
paced = PacedSender()
