"""
ChatSupervisor — `internal-*` 채널 1개당 1 인스턴스.

lifetime: 채널 status=running → 생성, idle/done → 제거 (pool.sync가 관리).
역할: 대화가 멈췄을 때 적절한 참가자를 nudge 해서 이어가게 함.
"""
from __future__ import annotations

import asyncio
import os
import re as _re
import subprocess
from datetime import datetime

import discord

from src import db, log_writer
from src.supervisors.base import Supervisor


def _judge_channel_conv(channel: str, question: str) -> str:
    """짧은 맥락 판단 — LLM 추상화 경유 (Haiku)."""
    recent = db.get_recent_messages(channel, limit=10)
    if not recent:
        return "no_data"
    from src.core.profile import get_user_id
    lines = []
    for r in recent:
        speaker = "유저" if r["speaker"] == get_user_id() else r["speaker"]
        lines.append(f"{speaker}: {r['message']}")
    conversation = "\n".join(lines[-8:])
    from src.llm import generate
    resp = generate(
        system="너는 대화 분석가. 질문에 한 단어로만 답해.",
        user=f"대화 기록:\n{conversation}\n\n질문: {question}",
        model="claude-haiku-4-5",
        agent_type="supervisor_judge",
        timeout=15,
        max_tokens=32,
        cacheable_system=True,
    )
    if resp.error:
        return "error"
    return (resp.text or "").strip().lower() or "error"


class ChatSupervisor(Supervisor):
    """특정 internal 채널 전담. running 동안만 살아있음."""

    kind = "channel"
    interval = 15.0

    @staticmethod
    def id_for(channel_name: str) -> str:
        return f"chat:{channel_name}"

    def __init__(self, channel_name: str):
        super().__init__(scope={"channel": channel_name})
        self.channel_name = channel_name
        self.id = ChatSupervisor.id_for(channel_name)
        self.display_name = f"대화 · {self._short_label(channel_name)}"
        self._last_nudge_time: float = 0.0
        self._nudge_cooldown: float = 90.0

    @staticmethod
    def _short_label(ch: str) -> str:
        # internal-dm-A-B → A·B, internal-group-A-B-C → A·B·C
        base = ch
        for prefix in ("internal-dm-", "internal-group-"):
            if base.startswith(prefix):
                base = base[len(prefix):]
                break
        return base.replace("-", "·")

    def should_exist(self) -> bool:
        """채널이 여전히 running 상태일 때만 유지."""
        try:
            conn = db.get_conn()
            row = conn.execute(
                "SELECT status FROM channels WHERE channel=?", (self.channel_name,)
            ).fetchone()
            conn.close()
            return bool(row and row["status"] == "running")
        except Exception:
            return False

    # ── check ─────────────────────────────────────────────

    async def check(self, ctx):
        guild = ctx.get("guild") if isinstance(ctx, dict) else None
        if guild is None:
            return

        # 참가자 추출
        try:
            conn = db.get_conn()
            row = conn.execute(
                "SELECT participants FROM channels WHERE channel=?", (self.channel_name,)
            ).fetchone()
            conn.close()
            if not row:
                return
            import json as _json
            parts = _json.loads(row["participants"] or "[]")
        except Exception:
            return
        if not parts:
            return

        # 참가자 중 thinking/speaking 이면 스킵
        if any(log_writer.is_thinking(p) or log_writer.is_speaking(p) for p in parts):
            return

        idle = self._get_idle_seconds()
        if idle < 20:
            return  # 대화 진행 중

        if not self._can_nudge():
            return

        loop = asyncio.get_event_loop()
        from src.core.prompts.en.supervisor_judge import CHAT_STUCK_QUESTION
        judgment = await loop.run_in_executor(None, lambda: _judge_channel_conv(
            self.channel_name, CHAT_STUCK_QUESTION
        ))
        if "멈춤" in judgment or "stopped" in judgment:
            target_id = self._pick_nudge_target(parts)
            if not target_id:
                return
            log_writer.system(f"[sup:{self.id}] 멈춤 — {target_id} 재촉")
            self._mark_nudged()
            ch = discord.utils.get(guild.text_channels, name=self.channel_name)
            if ch:
                await self._inject_and_send(
                    target_id, ch,
                    # 1인칭 self-talk — persona 가 지시문으로 오해하지 않도록.
                    "아 맞다 뭔가 얘기하려 했었는데."
                )

    def _pick_nudge_target(self, participants: list[str]) -> str | None:
        recent = db.get_recent_messages(self.channel_name, limit=1)
        if not recent:
            return participants[0] if participants else None
        last_speaker = recent[-1]["speaker"]
        for pid in participants:
            if pid != last_speaker:
                return pid
        return participants[0] if participants else None

    # ── 유틸 ──────────────────────────────────────────────

    def _can_nudge(self) -> bool:
        import time
        return (time.time() - self._last_nudge_time) > self._nudge_cooldown

    def _mark_nudged(self):
        import time
        self._last_nudge_time = time.time()

    def _get_idle_seconds(self) -> float:
        recent = db.get_recent_messages(self.channel_name, limit=1)
        if not recent:
            return 999.0
        try:
            last_dt = datetime.fromisoformat(recent[-1]["timestamp"])
            return (datetime.utcnow() - last_dt).total_seconds()
        except Exception:
            return 999.0

    async def _inject_and_send(self, agent_id: str, channel, instruction: str):
        if log_writer.is_thinking(agent_id) or log_writer.is_speaking(agent_id):
            return
        from src.bot import _get_channel_lock
        from src.bot.core import send_as_agent, _split_for_chat
        from src.core.runtime import runtime
        lock = _get_channel_lock(self.channel_name)
        if lock.locked():
            return
        async with lock:
            loop = asyncio.get_event_loop()
            responses = await loop.run_in_executor(
                None,
                lambda: runtime.generate_response_force(
                    agent_id, self.channel_name, instruction
                ),
            )
            cmd_pat = _re.compile(r'\[(?:CMD|QUERY|ACTION):[^\]]*\]')
            for resp in responses:
                clean = cmd_pat.sub('', resp).strip()
                if clean and clean != "..." and clean != "(무시)":
                    for part in _split_for_chat(clean):
                        await send_as_agent(channel, agent_id, part)
                        await asyncio.sleep(0.1)
