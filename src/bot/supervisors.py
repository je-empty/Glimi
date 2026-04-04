"""
Project Glimi — Supervisor 시스템

에이전트 뒤에서 동작하는 감시자들. 유저/에이전트에게 보이지 않음.
각 Supervisor는 특정 조건을 감시하고, 필요시 에이전트에게 내부 프롬프트를 주입.

확장: 새 Supervisor 클래스를 만들고 SUPERVISORS에 등록하면 자동으로 동작.
"""
import asyncio
import re as _re
from datetime import datetime

import discord
from discord.ext import tasks

from src import db, log_writer
from src.core.runtime import runtime
from src.bot import (
    bot, log, MGR_CHANNEL, MGR_SYSTEM_LOG, CREATOR_CHANNEL, MGR_ID,
)
from src.bot.core import send_as_agent, _split_for_chat


# ── 베이스 ──────────────────────────────────────────────

class Supervisor:
    """감시자 베이스 클래스"""
    name: str = "unnamed"
    interval: float = 15  # 초

    def should_run(self) -> bool:
        """이 감시자가 활성화돼야 하는지"""
        return False

    async def check(self, guild: discord.Guild):
        """매 interval마다 호출"""
        pass

    def is_done(self) -> bool:
        """완료 여부 — True면 자동 비활성화"""
        return False


# ── 온보딩 감시자 ────────────────────────────────────────

class OnboardingSupervisor(Supervisor):
    """온보딩 전 과정 감시 + 재촉"""
    name = "onboarding"
    interval = 15

    def should_run(self) -> bool:
        return db.get_meta("onboarding_phase") != "complete"

    def is_done(self) -> bool:
        return db.get_meta("onboarding_phase") == "complete"

    async def check(self, guild: discord.Guild):
        phase = db.get_meta("onboarding_phase")
        greeted = db.get_meta("yuna_greeted")

        # 에이전트 추론/전송 중이면 스킵
        CREATOR_ID = "agent-creator-001"
        busy_agents = [MGR_ID, CREATOR_ID]
        if any(log_writer.is_thinking(a) or log_writer.is_speaking(a) for a in busy_agents):
            return

        if not phase or phase == "":
            await self._check_profile_collection(guild, greeted)
        elif phase in ("channels_setup", "channels_done"):
            await self._check_channel_setup(guild)

    # ── 프로필 수집 단계 ──

    async def _check_profile_collection(self, guild, greeted):
        if not greeted:
            return  # 첫 인사 대기

        idle = self._get_idle_seconds(MGR_CHANNEL)
        if idle < 20:
            return  # 대화 진행 중

        # 프로필 충분한지 체크
        conn = db.get_conn()
        user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
        conn.close()
        user = dict(user) if user else {}

        has_mbti = bool(user.get("mbti"))
        has_bg = bool(user.get("background"))
        collected = sum([has_mbti, has_bg])

        if collected >= 2:
            # 조건 충족 — 강제 트리거
            log_writer.system("[sup:onboarding] 프로필수집 조건 충족 — 강제 트리거")
            from src.bot.mgr_system import _trigger_onboarding_phase2
            await _trigger_onboarding_phase2(guild)
            return

        if idle > 30:
            # 유나에게 재촉 (내면의 생각으로 주입)
            await self._nudge_yuna(guild,
                "프로필 수집을 마무리하고 다음 단계로 넘어가야겠다. "
                "아직 안 물어본 게 있으면 물어보고, 충분히 물어봤으면 마무리하자."
            )

    # ── 채널 세팅 단계 ──

    async def _check_channel_setup(self, guild):
        ch_names = {ch.name for ch in guild.text_channels}
        has_syslog = MGR_SYSTEM_LOG in ch_names
        has_creator = CREATOR_CHANNEL in ch_names

        if not has_syslog or not has_creator:
            return  # 채널 생성 진행 중

        # 하나 인사 여부
        CREATOR_ID = "agent-creator-001"
        creator_msgs = db.get_recent_messages(CREATOR_CHANNEL, limit=1)
        if not creator_msgs:
            return  # 하나 인사 대기

        # 하나→유나 보고 여부 (internal-dm 존재)
        has_report = any(
            n.startswith("internal-dm-") and ("유나" in n or "하나" in n)
            for n in ch_names
        )

        if has_report:
            # 유나가 온보딩완료를 보냈는지 체크
            idle = self._get_idle_seconds(MGR_CHANNEL)
            if idle > 45:
                await self._nudge_yuna(guild,
                    "하나한테 보고 받은 걸 전달해야겠다. "
                    "채널 구조도 설명해주고 온보딩 마무리하자."
                )
            return

        # 하나가 보고 안 함 — 멈춤 체크
        idle = self._get_idle_seconds(CREATOR_CHANNEL)
        if idle > 30:
            log_writer.system("[sup:onboarding] 하나 아이스브레이킹 멈춤 — 재촉")
            await self._nudge_agent(guild, CREATOR_ID, CREATOR_CHANNEL,
                "아이스브레이킹은 충분히 한 것 같다. "
                "에이전트 생성 얘기를 시작하고, 유나 언니한테 보고도 해야지."
            )

    # ── 유틸리티 ──

    def _get_idle_seconds(self, channel: str) -> float:
        recent = db.get_recent_messages(channel, limit=1)
        if not recent:
            return 999
        try:
            last_dt = datetime.fromisoformat(recent[-1]["timestamp"])
            return (datetime.now() - last_dt).total_seconds()
        except Exception:
            return 999

    async def _nudge_yuna(self, guild, system_msg: str):
        log_writer.system(f"[sup:onboarding] 유나 재촉")
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
        """에이전트에게 강제 지시 주입 (에이전트는 자기 내면의 생각으로 인식)"""
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response_force(
                agent_id, ch_name, instruction
            )
        )
        cmd_pat = _re.compile(r'\[(?:CMD|QUERY|ACTION):[^\]]*\]')
        for resp in responses:
            clean = cmd_pat.sub('', resp).strip()
            if clean:
                for part in _split_for_chat(clean):
                    await send_as_agent(channel, agent_id, part)
                    await asyncio.sleep(0.1)
                    db.log_message(ch_name, agent_id, part)


# ── 감시자 레지스트리 + 루프 ────────────────────────────

SUPERVISORS: list[Supervisor] = [
    OnboardingSupervisor(),
]

_active: list[Supervisor] = []
_pending_check: asyncio.Event | None = None


async def _run_checks():
    """활성 감시자 체크 실행"""
    if not bot.guilds:
        return
    guild = bot.guilds[0]

    for sup in list(_active):
        try:
            if sup.is_done():
                _active.remove(sup)
                log_writer.system(f"[sup:{sup.name}] 완료 — 비활성화")
                continue
            await sup.check(guild)
        except Exception as e:
            log_writer.system(f"[sup:{sup.name}] 오류: {e}")


async def notify_idle(channel_name: str):
    """에이전트 응답 완료 후 호출 — 일정 시간 후 유저 응답 없으면 감시자 실행"""
    if not _active:
        return

    # 관련 채널인지 체크
    relevant = any(
        channel_name in (MGR_CHANNEL, CREATOR_CHANNEL) or channel_name.startswith("internal-")
        for _ in [1]
    )
    if not relevant:
        return

    await asyncio.sleep(15)  # 15초 대기 — 유저 응답 기다림

    # 대기 후에도 마지막 메시지가 에이전트 것이면 (유저가 응답 안 함) → 체크
    recent = db.get_recent_messages(channel_name, limit=1)
    if recent:
        from src.core.profile import get_user_id
        last_speaker = recent[-1]["speaker"]
        if last_speaker != get_user_id():
            # 에이전트가 마지막 발화 → 유저 응답 없음 → 감시자 체크
            await _run_checks()


def start_supervisors():
    """필요한 감시자 활성화"""
    global _active
    _active = [s for s in SUPERVISORS if s.should_run()]
    if _active:
        names = [s.name for s in _active]
        log_writer.system(f"[supervisor] 활성화: {', '.join(names)}")
    else:
        log_writer.system("[supervisor] 활성화할 감시자 없음")
