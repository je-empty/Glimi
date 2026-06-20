"""
PacedSender — 에이전트 메시지가 실제 사람 타이핑처럼 페이스 조절되어 Discord에 나가도록.

문제:
    Claude CLI가 응답 여러 줄을 빠르게 쏟아내고, 그룹 채팅에서 여러 에이전트가
    동시에 스트리밍하면 webhook 전송이 뭉텅이로 쌓여서 우다다다 한꺼번에 보임.

해결:
    채널별로 단일 FIFO 큐 + 워커. 각 메시지 전송 전후로 길이 비례 딜레이 + gap.
    에이전트 전환 시 리드인 딜레이 추가 (생각하는 시간).

사용:
    await paced.enqueue(channel, agent_id, content, send_fn)
    # send_fn은 async callable — 실제 webhook.send 등

    # 채널 큐 대기 없이 즉시 보내야 할 경우:
    await paced.send_immediate(send_fn)
"""
import asyncio
import random
from typing import Awaitable, Callable, Optional

import discord

from community.bot import log


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
        channel: discord.TextChannel,
        agent_id: str,
        content: str,
        send_fn: Callable[[], Awaitable[None]],
    ):
        """메시지를 채널 큐에 enqueue. 워커는 필요 시 자동 시작."""
        if not channel:
            # 채널 없으면 바로 전송 (fallback)
            try:
                await send_fn()
            except Exception as e:
                log.warning(f"[PacedSender] direct send fail: {e}")
            return

        ch_name = getattr(channel, "name", None) or str(getattr(channel, "id", "?"))
        q = await self._ensure_worker(ch_name, channel)
        await q.put((agent_id, content, send_fn))

    async def _ensure_worker(self, ch_name: str, channel) -> asyncio.Queue:
        async with self._lock:
            q = self._queues.get(ch_name)
            if q is None:
                q = asyncio.Queue()
                self._queues[ch_name] = q
                self._workers[ch_name] = asyncio.create_task(
                    self._worker(ch_name, channel),
                    name=f"paced-sender:{ch_name}",
                )
            return q

    async def _worker(self, ch_name: str, channel):
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
                log.warning(f"[PacedSender] send fail #{ch_name}: {e}")

            # 같은 에이전트 연쇄 간 gap
            await asyncio.sleep(random.uniform(*INTRA_AGENT_GAP))

            last_agent = agent_id
            self._last_agent[ch_name] = agent_id

    async def flush(self, channel) -> None:
        """해당 채널 큐가 완전히 비워질 때까지 대기 (최대 30초)."""
        ch_name = getattr(channel, "name", None) or str(getattr(channel, "id", "?"))
        q = self._queues.get(ch_name)
        if q is None:
            return
        for _ in range(300):  # 100ms * 300 = 30s 상한
            if q.empty():
                return
            await asyncio.sleep(0.1)


# 싱글턴
paced = PacedSender()
