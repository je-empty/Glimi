"""
TutorialFlowSupervisor — 튜토리얼 씬 phase 전이·재촉·자동 완료 담당.

- kind: "scene"
- id: "tutorial.flow"
- lifetime: scene.is_active()에 따라 pool이 자동 생성·제거.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime

import discord

from src import db, log_writer
from src.core.runtime import runtime
from src.bot import (
    MGR_CHANNEL,
    MGR_SYSTEM_LOG,
    CREATOR_CHANNEL,
    MGR_ID,
)
from src.bot.core import send_as_agent, _split_for_chat
from src.supervisors.base import Supervisor


def _judge_conversation(channel: str, question: str) -> str:
    """대화 맥락을 haiku에게 판단 요청 (저비용). LLM 추상화 경유."""
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


class TutorialFlowSupervisor(Supervisor):
    """튜토리얼 씬 전 과정 감시 + 재촉 + 자동 완료. scene-scoped singleton."""

    id = "tutorial.flow"
    display_name = "튜토리얼 · 흐름"
    kind = "scene"
    interval = 30.0

    def __init__(self, scene):
        super().__init__(scope={"scene_id": scene.id})
        self.scene = scene
        self._last_nudge_time: float = 0
        self._nudge_cooldown: float = 120

    def should_exist(self) -> bool:
        return self.scene.is_active()

    def _can_nudge(self) -> bool:
        import time
        return (time.time() - self._last_nudge_time) > self._nudge_cooldown

    def _mark_nudged(self):
        import time
        self._last_nudge_time = time.time()

    async def check(self, ctx):
        guild = ctx.get("guild") if isinstance(ctx, dict) else None
        if guild is None:
            return
        # 에이전트 추론/전송 중이면 스킵
        CREATOR_ID = "agent-creator-001"
        busy_agents = [MGR_ID, CREATOR_ID]
        if any(log_writer.is_thinking(a) or log_writer.is_speaking(a) for a in busy_agents):
            return

        phase = self.scene.current_phase()
        if phase in ("greet", "collect_profile"):
            await self._check_profile_collection(guild, phase)
        elif phase in ("channels_setup", "channels_done"):
            await self._check_channel_setup(guild)

    # ── 프로필 수집 단계 ────────────────────────────────

    async def _check_profile_collection(self, guild, phase):
        if phase == "greet":
            return  # 첫 인사 대기

        idle = self._get_idle_seconds(MGR_CHANNEL)
        if idle < 15:
            return  # 대화 진행 중

        conn = db.get_conn()
        user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
        conn.close()
        user = dict(user) if user else {}

        has_mbti = bool(user.get("mbti"))
        has_bg = bool(user.get("background"))

        # hobby는 personality(JSON) 하위 필드
        import json as _json
        pers = user.get("personality")
        if isinstance(pers, str):
            try:
                pers = _json.loads(pers)
            except Exception:
                pers = {}
        pers = pers or {}
        has_hobby = bool(pers.get("hobby")) or bool(pers.get("keywords"))

        collected = sum([has_mbti, has_bg, has_hobby])

        # 유저 턴 수 — 너무 짧게 몇 번 대화하고 Phase 2로 넘어가지 않도록
        from src.core.profile import get_user_id
        mgr_msgs = db.get_recent_messages(MGR_CHANNEL, limit=50)
        user_turns = sum(1 for m in mgr_msgs if m.get("speaker") == get_user_id())

        # 조건: mbti·직업·취미 중 2개 이상 + 유저 6턴 이상.
        # 둘 다 만족해야 진짜로 Phase 2 트리거 (조기 점프 방지).
        if collected >= 2 and user_turns >= 6:
            log_writer.system(
                f"[sup:tutorial] 프로필수집 조건 충족 "
                f"(fields={collected}/3, user_turns={user_turns}) — 강제 트리거"
            )
            from src.scenes.tutorial.handlers import trigger_phase2
            await trigger_phase2(guild)
            return

        recent = db.get_recent_messages(MGR_CHANNEL, limit=5)
        if not recent:
            return
        last_speaker = recent[-1].get("speaker", "")
        if last_speaker == MGR_ID:
            return  # 유나가 마지막 말했으면 대기

        if not self._can_nudge():
            return

        loop = asyncio.get_event_loop()
        from src.core.prompts.en.supervisor_judge import TUTORIAL_PROFILE_COLLECTION_QUESTION
        judgment = await loop.run_in_executor(None, lambda: _judge_conversation(
            MGR_CHANNEL, TUTORIAL_PROFILE_COLLECTION_QUESTION
        ))

        if judgment in ("미응답", "no_response", "unanswered"):
            log_writer.system(f"[sup:tutorial] 판단: {judgment} — 유나 응답 유도")
            self._mark_nudged()
            await self._nudge_yuna(guild,
                "유저가 방금 뭔가 말했는데 아직 반응을 안 한 것 같다. "
                "자연스럽게 대답해주자."
            )
        elif judgment in ("잡담", "chatting"):
            log_writer.system(f"[sup:tutorial] 판단: {judgment} — 유나 복귀 유도")
            self._mark_nudged()
            await self._nudge_yuna(guild,
                "잡담이 길어진 것 같다. "
                "자연스럽게 화제를 돌려서 다음 프로필 질문으로 넘어가자. "
                "갑자기 전환하지 말고 대화 흐름에 맞춰서."
            )

    # ── 채널 세팅 단계 ──────────────────────────────────

    async def _check_channel_setup(self, guild):
        ch_names = {ch.name for ch in guild.text_channels}
        has_syslog = MGR_SYSTEM_LOG in ch_names
        has_creator = CREATOR_CHANNEL in ch_names
        if not has_syslog or not has_creator:
            # 재기동·충돌 등으로 phase=channels_setup 인데 채널이 아직 없을 수 있음.
            # 원래 trigger_phase2 가 setup_channels 를 돌리는데, supervisor 가 채널 조건으로
            # 일찍 return 하면 아무도 진행을 못 시킴 → Phase 2 영구 stall.
            # 한 번만 setup_channels 재진입 (setup_channels 는 phase=channels_done/complete 면
            # 알아서 종료하므로 중복 실행 안전).
            phase = self.scene.current_phase()
            if phase == "channels_setup" and self._can_nudge():
                self._mark_nudged()
                log_writer.system(
                    f"[sup:tutorial] 재개: phase=channels_setup 인데 채널 미생성 — setup_channels 재진입"
                )
                from src.scenes.tutorial.handlers import setup_channels
                try:
                    await setup_channels(guild)
                except Exception as e:
                    log_writer.system(f"❌ [sup:tutorial] 재개 실패: {type(e).__name__}: {e}")
            return

        CREATOR_ID = "agent-creator-001"
        creator_msgs = db.get_recent_messages(CREATOR_CHANNEL, limit=1)
        if not creator_msgs:
            return

        conn = db.get_conn()
        persona_count = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE type='persona'"
        ).fetchone()[0]
        db_channels = [r[0] for r in conn.execute("SELECT channel FROM channels").fetchall()]
        conn.close()

        if persona_count == 0:
            return  # 하나 작업 중

        has_report = any(
            n.startswith("internal-dm-") and ("유나" in n or "하나" in n)
            for n in db_channels
        )

        if has_report:
            # 자동 finish_tutorial — LLM이 프롬프트 받고도 finish 호출 안 하는 케이스가
            # 거의 매 사이클 반복. 조건 만족하면 supervisor가 직접 종료시킴.
            #
            # 조건: hana 보고 채널 + persona 생성됨 + dm-{persona} 채널 존재
            # (= hana가 create_agent_profile + request_dm 까지 완료한 신호).
            # idle 조건 제거 — 오너가 계속 대화해도 튜토리얼은 완료 가능해야 함.
            from src.bot import MGR_ID
            persona_names = [r[0] for r in db.get_conn().execute(
                "SELECT name FROM agents WHERE type='persona'"
            ).fetchall()]
            if persona_names:
                persona_dm_ready = any(
                    f"dm-{n}" in db_channels for n in persona_names
                )
                recent_mgr = db.get_recent_messages(MGR_CHANNEL, limit=15)
                mgr_text = " ".join(m.get("message", "") for m in recent_mgr)
                yuna_mentioned_friend = any(n in mgr_text for n in persona_names)
                if persona_dm_ready and yuna_mentioned_friend:
                    log_writer.system(
                        "[sup:tutorial] 자동 finish_tutorial — "
                        f"{', '.join(persona_names)} 생성 + DM 채널 완성 확인"
                    )
                    from src.scenes.tutorial.handlers import complete_tutorial
                    await complete_tutorial()
                    return
                # DM 까진 왔는데 유나가 mgr-dashboard에 아직 안내를 안 했다 → nudge
                if persona_dm_ready and not yuna_mentioned_friend and self._can_nudge():
                    self._mark_nudged()
                    await self._nudge_yuna(guild,
                        f"하나가 {', '.join(persona_names)} 프로필 만들었고 "
                        f"dm 채널까지 열렸어. mgr-dashboard 에서 오너한테 한 줄 소개하고 "
                        f"바로 finish_tutorial 호출해서 튜토리얼 마무리하자."
                    )
                    return

            idle = self._get_idle_seconds(MGR_CHANNEL)
            if idle > 60 and self._can_nudge():
                self._mark_nudged()
                await self._nudge_yuna(guild,
                    "하나한테 보고 받은 걸 전달해야겠다. "
                    "채널 구조도 설명해주고 튜토리얼 마무리하자."
                )
            return

        for n in ch_names:
            if n.startswith("internal-dm-") and ("유나" in n or "하나" in n):
                int_status = db.get_channel_status(n)
                if int_status.get("status") == "running":
                    return  # CS에 위임

        idle = self._get_idle_seconds(CREATOR_CHANNEL)
        if idle < 30:
            return

        creator_recent = db.get_recent_messages(CREATOR_CHANNEL, limit=3)
        if creator_recent:
            last_speaker = creator_recent[-1].get("speaker", "")
            if last_speaker == CREATOR_ID:
                return

        creator_all = db.get_recent_messages(CREATOR_CHANNEL, limit=20)
        if len(creator_all) < 8:
            return

        loop = asyncio.get_event_loop()
        from src.core.prompts.en.supervisor_judge import TUTORIAL_CREATOR_ICEBREAK_QUESTION
        judgment = await loop.run_in_executor(None, lambda: _judge_conversation(
            CREATOR_CHANNEL, TUTORIAL_CREATOR_ICEBREAK_QUESTION
        ))

        if judgment in ("충분", "enough", "done") and self._can_nudge():
            log_writer.system(f"[sup:tutorial] 하나 판단: {judgment} — 재촉")
            self._mark_nudged()
            await self._nudge_agent(guild, CREATOR_ID, CREATOR_CHANNEL,
                "아이스브레이킹이 충분했으면 에이전트 생성 얘기 꺼내고 유나한테 보고. "
                "이미 보고했으면 다시 보내지 마."
            )

    # ── 유틸리티 ────────────────────────────────────────

    def _get_idle_seconds(self, channel: str) -> float:
        recent = db.get_recent_messages(channel, limit=1)
        if not recent:
            return 999
        try:
            last_dt = datetime.fromisoformat(recent[-1]["timestamp"])
            return (datetime.utcnow() - last_dt).total_seconds()
        except Exception:
            return 999

    async def _nudge_yuna(self, guild, system_msg: str):
        log_writer.system(f"[sup:tutorial] 유나 재촉")
        mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
        if not mgr_ch:
            return
        await self._inject_and_send(MGR_ID, MGR_CHANNEL, mgr_ch, system_msg)

    async def _nudge_agent(self, guild, agent_id: str, ch_name: str, system_msg: str):
        ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not ch:
            return
        await self._inject_and_send(agent_id, ch_name, ch, system_msg)

    async def _inject_and_send(self, agent_id, ch_name, channel, instruction):
        if log_writer.is_thinking(agent_id) or log_writer.is_speaking(agent_id):
            log_writer.system(f"[sup:{self.name}] {agent_id} 이미 추론 중 — 강제 지시 스킵")
            return

        from src.bot import _get_channel_lock
        lock = _get_channel_lock(ch_name)
        if lock.locked():
            log_writer.system(f"[sup:{self.name}] #{ch_name} 채널 잠금 중 — 강제 지시 스킵")
            return

        async with lock:
            loop = asyncio.get_event_loop()
            responses = await loop.run_in_executor(
                None,
                lambda: runtime.generate_response_force(
                    agent_id, ch_name, instruction
                )
            )
            sent_count = 0
            for resp in responses:
                clean = resp.strip()
                if clean and clean != "..." and clean != "(무시)":
                    for part in _split_for_chat(clean):
                        await send_as_agent(channel, agent_id, part)
                        await asyncio.sleep(0.1)
                        sent_count += 1
            if sent_count == 0:
                log_writer.system(f"[sup:{self.name}] {agent_id} 재촉 응답 없음 (에이전트가 불필요 판단)")
