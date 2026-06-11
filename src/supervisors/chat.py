"""
ChatSupervisor — `internal-*` 채널 1개당 1 인스턴스.

lifetime: 채널 status=running → 생성, idle/done → 제거 (pool.sync가 관리).
역할: 대화가 멈췄을 때 적절한 참가자를 nudge 해서 이어가게 함.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from datetime import datetime

import discord

from src import db, log_writer
from src.supervisors.base import Supervisor
# universe-scoped 헬퍼들 — runtime 과 공유 (src/core/scoping.py 로 이전됨)
from src.core.scoping import (
    looks_hallucinated as _looks_hallucinated,
    owner_recent_end_signal as _owner_recent_end_signal_core,
    owner_recent_status as _owner_recent_status_core,
)


# Wrapper for backward compat — chat.py 안에서 _owner_recent_end_signal / _owner_recent_status
# 호출하는 코드 그대로 두되 src.core.scoping 의 함수를 alias 로 노출.
_owner_recent_end_signal = _owner_recent_end_signal_core
_owner_recent_status = _owner_recent_status_core


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
        # internal-dm-A-B → A·B, internal-group-A-B-C → A·B·C, group-A-B → A·B
        base = ch
        # 긴 prefix 우선 — internal-group- 이 group- 보다 먼저 매칭되어야 함
        for prefix in ("internal-dm-", "internal-group-", "group-"):
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

        # Quiet hours (23:00~06:59 KST) — 새벽 시간대 nudge 금지.
        # 환각 빈발 시간대 + 사용자 부재 시간 자율 대화 폭주 차단.
        from src.core.scoping import is_quiet_hour, quiet_hour_label
        if is_quiet_hour():
            log_writer.system(
                f"[sup:{self.id}] nudge skip — quiet hour ({quiet_hour_label()})"
            )
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

        # 현재 채널의 페르소나 (오너 제외) — universe scoping 의 기준.
        from src.core.profile import get_user_id
        owner_id = get_user_id()
        here_personas = {p for p in parts if p and p != owner_id}

        # 오너 종료 시그널 cooldown — universe-scoped.
        # _owner_recent_end_signal 은 here_personas 가 함께 있던 채널의 오너 발화만 검색.
        # SAO 페르소나 채널이면 SAO 관련 채널만, 홀로라이브 페르소나는 자기 채널만.
        end_sig = _owner_recent_end_signal(here_personas, within_hours=6.0)
        if end_sig:
            hours_ago, msg, src_ch = end_sig
            log_writer.system(
                f"[sup:{self.id}] nudge skip — 오너 {hours_ago:.1f}h 전 #{src_ch} 종료 발화: \"{msg[:40]}\""
            )
            self._mark_nudged()  # cooldown 의도적으로 소비 — 곧바로 재시도 방지
            return

        loop = asyncio.get_event_loop()
        from src.core.prompts.en.supervisor_judge import CHAT_STUCK_QUESTION
        judgment = await loop.run_in_executor(None, lambda: _judge_channel_conv(
            self.channel_name, CHAT_STUCK_QUESTION()
        ))
        if "멈춤" in judgment or "stopped" in judgment:
            target_id = self._pick_nudge_target(parts)
            if not target_id:
                return
            log_writer.system(f"[sup:{self.id}] 멈춤 — {target_id} 재촉")
            self._mark_nudged()
            ch = discord.utils.get(guild.text_channels, name=self.channel_name)
            if ch:
                # 1인칭 self-talk — persona 가 지시문으로 오해하지 않도록.
                # 새 주제 유도: 같은 대화 재탕 방지. 여러 seed 중 랜덤.
                import random as _r
                seed = _r.choice([
                    "(아 이따 다른 얘기 꺼내야지 — 뭐 재밌는 일 있었나?)",
                    "(뭔가 분위기 바꿀 얘기 하나 던져볼까)",
                    "(근데 요즘 관심사 얘기 안 해봤네)",
                    "(주말 계획 같은 거 물어볼까)",
                ])
                # 환각 발명 차단 가드 — internal-* 채널은 오너 부재라 페르소나가
                # 흐름 메우려 "방금 DM 왔어" 같은 가짜 이벤트 발명하는 회귀 빈발.
                guard = (
                    " [현실 grounding 엄수] 위 대화 이력에 실제로 적힌 것만 언급할 것. "
                    "다음 발명 절대 금지: '방금/지금/막 누가 DM/메시지/연락 왔어', "
                    "'아빠/엄마/오빠가 보냈어', '친구가 방금 알려줬어', "
                    "'지금 누가 뭐 한대'. 할 말 없으면 평범한 안부·근황·감정 공유로 풀어."
                )
                # 오너 최근 상태 — universe-scoped (here_personas 와 함께 있던 채널만).
                # SAO 페르소나는 SAO 관련 채널의 오너 발화만 보고, 홀로라이브 페르소나는
                # 자기 채널의 오너 발화만 봄. universe 분리 자동 처리.
                owner_status = _owner_recent_status(here_personas)
                await self._inject_and_send(target_id, ch, seed + guard + owner_status)

    def _pick_nudge_target(self, participants: list[str]) -> str | None:
        """nudge 대상 결정 — 마지막 발화자 외 에이전트 1명.
        오너(user_id) 는 generate_response_force 가 활성화 못 시켜 빈 응답이라
        반드시 제외. 'agent-' prefix 로 에이전트만 필터.
        group-* 채널처럼 오너가 participants 에 포함된 경우 핵심.
        """
        agent_parts = [p for p in participants if p and p.startswith("agent-")]
        if not agent_parts:
            return None
        recent = db.get_recent_messages(self.channel_name, limit=1)
        if not recent:
            return agent_parts[0]
        last_speaker = recent[-1]["speaker"]
        for pid in agent_parts:
            if pid != last_speaker:
                return pid
        return agent_parts[0]

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
            log_writer.system(
                f"[sup:{self.id}] nudge skip — {agent_id} 가 다른 채널에서 응답 중"
            )
            return
        from src.bot import _get_channel_lock
        from src.bot.core import send_as_agent, _split_for_chat
        from src.core.runtime import runtime
        lock = _get_channel_lock(self.channel_name)
        if lock.locked():
            log_writer.system(f"[sup:{self.id}] nudge skip — channel lock busy")
            return
        async with lock:
            loop = asyncio.get_event_loop()
            responses = await loop.run_in_executor(
                None,
                lambda: runtime.generate_response_force(
                    agent_id, self.channel_name, instruction
                ),
            )
            # 환각 필터 — 명백한 발명 이벤트 ("방금 DM 왔어" 등) 차단.
            # internal-* 채널은 오너 부재라 컨텍스트 검증이 약함 → post-hoc regex 차단이
            # 가장 신뢰할 만한 안전망. borderline 은 통과시켜 false-positive 최소화.
            kept: list[str] = []
            rejected: list[tuple[str, str]] = []
            for resp in responses:
                clean = resp.strip()
                if not clean or clean in ("...", "(무시)"):
                    continue
                reason = _looks_hallucinated(clean)
                if reason:
                    rejected.append((clean[:60], reason))
                else:
                    kept.append(clean)
            if rejected:
                preview = " | ".join(f"({r}) [{c}]" for c, r in rejected[:3])
                log_writer.system(
                    f"[sup:{self.id}] 환각 필터 — {len(rejected)}건 차단: {preview}"
                )

            sent = 0
            for clean in kept:
                for part in _split_for_chat(clean):
                    await send_as_agent(channel, agent_id, part)
                    await asyncio.sleep(0.1)
                    sent += 1
            if sent == 0:
                # nudge 가 어떤 응답을 만들었지만 디스코드 송출 0 — 진단용 로그.
                # 빈 list (CLI 실패/타임아웃), 모든 라인이 "..." 또는 "(무시)" 등
                # 모든 라인이 필터 (환각/claude_error/json/tools) 에 걸려 drop 된 경우 포함.
                log_writer.system(
                    f"[sup:{self.id}] nudge 무송출 — {agent_id}: "
                    f"responses={len(responses)}, hallu_rejected={len(rejected)}"
                )
