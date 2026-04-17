"""
Project Glimi — Supervisor 시스템

에이전트 뒤에서 동작하는 감시자들. 유저/에이전트에게 보이지 않음.
각 Supervisor는 특정 조건을 감시하고, 필요시 에이전트에게 내부 프롬프트를 주입.

확장: 새 Supervisor 클래스를 만들고 SUPERVISORS에 등록하면 자동으로 동작.
"""
import asyncio
import os
import re as _re
import subprocess
from datetime import datetime

import discord
from discord.ext import tasks

from src import db, log_writer
from src.core.runtime import runtime
from src.bot import (
    bot, log, MGR_CHANNEL, MGR_SYSTEM_LOG, CREATOR_CHANNEL, MGR_ID,
)
from src.bot.core import send_as_agent, _split_for_chat


def _judge_conversation(channel: str, question: str) -> str:
    """대화 맥락을 haiku에게 판단 요청 (저비용)"""
    recent = db.get_recent_messages(channel, limit=10)
    if not recent:
        return "no_data"

    from src.core.profile import get_user_id
    lines = []
    for r in recent:
        speaker = "유저" if r["speaker"] == get_user_id() else r["speaker"]
        lines.append(f"{speaker}: {r['message']}")
    conversation = "\n".join(lines[-8:])

    prompt = f"대화 기록:\n{conversation}\n\n질문: {question}\n한 단어로만 답해."

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text",
             "--model", "claude-haiku-4-5-20251001"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
        )
        return result.stdout.strip().lower() if result.returncode == 0 else "error"
    except Exception:
        return "error"


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
    interval = 30  # 30초 간격 (15초는 너무 빈번)

    def __init__(self):
        super().__init__()
        self._last_nudge_time: float = 0  # 마지막 재촉 시각
        self._nudge_cooldown: float = 120  # 재촉 쿨다운 2분

    def should_run(self) -> bool:
        return db.get_meta("onboarding_phase") != "complete"

    def is_done(self) -> bool:
        return db.get_meta("onboarding_phase") == "complete"

    def _can_nudge(self) -> bool:
        """쿨다운 체크 — 마지막 재촉 후 일정 시간 경과해야 다시 재촉 가능"""
        import time
        return (time.time() - self._last_nudge_time) > self._nudge_cooldown

    def _mark_nudged(self):
        import time
        self._last_nudge_time = time.time()

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
        if idle < 15:
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
            log_writer.system("[sup:onboarding] 프로필수집 조건 충족 — 강제 트리거")
            from src.bot.mgr_system import _trigger_onboarding_phase2
            await _trigger_onboarding_phase2(guild)
            return

        # 마지막 발화자 확인
        recent = db.get_recent_messages(MGR_CHANNEL, limit=5)
        if not recent:
            return

        last_speaker = recent[-1].get("speaker", "")

        # 유나가 마지막으로 말했고 유저 응답 없으면 → 기다림 (재촉 안 함)
        if last_speaker == MGR_ID:
            return

        # 쿨다운 체크
        if not self._can_nudge():
            return

        # 유저가 마지막으로 말한 뒤 유나가 아직 대답 안 한 경우에만 개입
        # (유나가 응답을 안 하고 있는 상황 = 시스템 문제이거나 유나가 멈춤)
        # 대화 맥락 판단 (haiku)
        loop = asyncio.get_event_loop()
        judgment = await loop.run_in_executor(None, lambda: _judge_conversation(
            MGR_CHANNEL,
            "최근 대화를 보고 판단해줘. "
            "유저가 마지막에 말했는데 에이전트가 아직 반응하지 않은 건가? "
            "아니면 잡담으로 빠져서 프로필 수집이 진행되지 않는 건가? "
            "'미응답', '잡담', '진행중' 중 하나로."
        ))

        if judgment in ("미응답", "no_response", "unanswered"):
            # 유나가 유저 메시지에 반응 못한 상태 → 부드럽게 지시
            log_writer.system(f"[sup:onboarding] 판단: {judgment} — 유나 응답 유도")
            self._mark_nudged()
            await self._nudge_yuna(guild,
                "유저가 방금 뭔가 말했는데 아직 반응을 안 한 것 같다. "
                "자연스럽게 대답해주자."
            )
        elif judgment in ("잡담", "chatting"):
            log_writer.system(f"[sup:onboarding] 판단: {judgment} — 유나 복귀 유도")
            self._mark_nudged()
            await self._nudge_yuna(guild,
                "잡담이 길어진 것 같다. "
                "자연스럽게 화제를 돌려서 다음 프로필 질문으로 넘어가자. "
                "갑자기 전환하지 말고 대화 흐름에 맞춰서."
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

        # 페르소나 에이전트 존재 여부 — 하나가 최소 1명 생성했어야 Phase 3 진행
        # (이거 없으면 "채널 구조 설명" 재촉하면 유나가 있지도 않은 dm 채널 환각함)
        conn = db.get_conn()
        persona_count = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE type='persona'"
        ).fetchone()[0]
        db_channels = [r[0] for r in conn.execute("SELECT channel FROM channels").fetchall()]
        conn.close()

        if persona_count == 0:
            # 하나 작업 중. 유나 재촉하면 안 됨 (환각 방지)
            return

        # 하나→유나 보고 여부 — DB 기준 (Discord stale 채널 영향 제거)
        has_report = any(
            n.startswith("internal-dm-") and ("유나" in n or "하나" in n)
            for n in db_channels
        )

        if has_report:
            # 유나가 온보딩완료를 보냈는지 체크
            idle = self._get_idle_seconds(MGR_CHANNEL)
            if idle > 60 and self._can_nudge():
                self._mark_nudged()
                await self._nudge_yuna(guild,
                    "하나한테 보고 받은 걸 전달해야겠다. "
                    "채널 구조도 설명해주고 온보딩 마무리하자."
                )
            return

        # internal-dm이 running 상태면 ChannelConversationSupervisor가 관리 → 여기선 대기
        for n in ch_names:
            if n.startswith("internal-dm-") and ("유나" in n or "하나" in n):
                int_status = db.get_channel_status(n)
                if int_status.get("status") == "running":
                    return  # CS에 위임

        # 하나가 보고 안 함 — 대화 활발하면 대기
        idle = self._get_idle_seconds(CREATOR_CHANNEL)
        if idle < 30:
            return  # 아직 대화 중 — 서두르지 않음

        # 마지막 발화자가 에이전트(하나)이고 유저가 답 안 한 상태 → 재촉하지 않음
        creator_recent = db.get_recent_messages(CREATOR_CHANNEL, limit=3)
        if creator_recent:
            last_speaker = creator_recent[-1].get("speaker", "")
            if last_speaker == CREATOR_ID:
                return  # 하나가 말했고 유저가 아직 답 안 함 — 기다림

        # 하나 채널 대화가 최소 5턴 미만이면 아직 아이스브레이킹 중
        creator_all = db.get_recent_messages(CREATOR_CHANNEL, limit=20)
        if len(creator_all) < 8:
            return  # 대화 부족 — 더 기다림

        loop = asyncio.get_event_loop()
        judgment = await loop.run_in_executor(None, lambda: _judge_conversation(
            CREATOR_CHANNEL,
            "크리에이터가 아이스브레이킹을 충분히 했나? "
            "에이전트 생성까지 진행됐나? "
            "'충분', '진행중' 중 하나로."
        ))

        if judgment in ("충분", "enough", "done") and self._can_nudge():
            log_writer.system(f"[sup:onboarding] 하나 판단: {judgment} — 재촉")
            self._mark_nudged()
            await self._nudge_agent(guild, CREATOR_ID, CREATOR_CHANNEL,
                "아이스브레이킹이 충분했으면 에이전트 생성 얘기 꺼내고 유나 언니한테 보고. "
                "이미 보고했으면 다시 보내지 마."
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
        """에이전트에게 강제 지시 주입 (에이전트는 자기 내면의 생각으로 인식).
        에이전트가 판단해서 메시지를 안 보낼 수도 있음."""
        # 에이전트가 이미 추론/전송 중이면 스킵 (race condition 방지)
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
            cmd_pat = _re.compile(r'\[CMD:((?:[^\[\]]|\[[^\]]*\])*)\]')
            query_pat = _re.compile(r'\[QUERY:((?:[^\[\]]|\[[^\]]*\])*)\]')
            all_tag_pat = _re.compile(r'\[(?:CMD|QUERY|ACTION):[^\]]*\]')
            sent_count = 0
            for resp in responses:
                # CMD/QUERY 실행 (mgr만)
                if agent_id == MGR_ID and (cmd_pat.search(resp) or query_pat.search(resp)):
                    from src.bot.mgr_system import parse_and_execute_actions
                    guild = channel.guild
                    if guild:
                        await parse_and_execute_actions(channel, [resp], guild)

                clean = all_tag_pat.sub('', resp).strip()
                # "..." 또는 빈 응답은 에이전트가 아무 말 안 하기로 한 것
                if clean and clean != "..." and clean != "(무시)":
                    for part in _split_for_chat(clean):
                        await send_as_agent(channel, agent_id, part)
                        await asyncio.sleep(0.1)
                        sent_count += 1
            if sent_count == 0:
                log_writer.system(f"[sup:{self.name}] {agent_id} 재촉 응답 없음 (에이전트가 불필요 판단)")


# ── 채널 대화 감시자 ────────────────────────────────────

class ChannelConversationSupervisor(Supervisor):
    """internal 채널 대화 감시 — running 상태인 채널에서 대화가 멈추면 재촉"""
    name = "channel-conv"
    interval = 15

    def should_run(self) -> bool:
        # running 상태 채널이 있으면 활성화
        return bool(self._get_running_channels())

    def is_done(self) -> bool:
        return not self._get_running_channels()

    def _get_running_channels(self) -> list[dict]:
        """running 상태인 internal 채널 목록"""
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT channel, participants, status, max_turns, current_turn FROM channels WHERE status='running'"
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            ch = r["channel"]
            # internal 채널만 (dm-*, group-*은 유저 참여라 제외)
            if ch.startswith("internal-"):
                import json as _json
                try:
                    parts = _json.loads(r["participants"])
                except Exception:
                    parts = []
                result.append({
                    "channel": ch,
                    "participants": parts,
                    "max_turns": r["max_turns"],
                    "current_turn": r["current_turn"],
                })
        return result

    async def check(self, guild: discord.Guild):
        channels = self._get_running_channels()
        for ch_info in channels:
            ch_name = ch_info["channel"]
            participants = ch_info["participants"]

            # 참가자 중 thinking/speaking 중이면 스킵
            if any(log_writer.is_thinking(p) or log_writer.is_speaking(p) for p in participants):
                continue

            # idle 시간 체크
            idle = self._get_idle_seconds(ch_name)
            if idle < 20:
                continue  # 아직 대화 진행 중

            # 맥락 판단 (haiku)
            loop = asyncio.get_event_loop()
            judgment = await loop.run_in_executor(None, lambda ch=ch_name: _judge_conversation(
                ch,
                "이 대화가 자연스럽게 이어지고 있나? 아니면 한쪽이 멈춰서 대화가 안 되고 있나? "
                "멈춤이면 누가 다음에 말해야 하나? '진행중', '멈춤:에이전트이름' 중 하나로."
            ))

            if "멈춤" in judgment or "stopped" in judgment:
                # 누구한테 재촉할지 판단
                target_id = self._pick_nudge_target(ch_name, participants, judgment)
                if target_id:
                    log_writer.system(f"[sup:channel-conv] #{ch_name} 멈춤 — {target_id} 재촉")
                    ch = discord.utils.get(guild.text_channels, name=ch_name)
                    if ch:
                        await self._inject_and_send(target_id, ch_name, ch,
                            "대화가 좀 멈춘 것 같다. 상대가 말을 기다리는 것 같으니 자연스럽게 이어가자."
                        )

    def _pick_nudge_target(self, ch_name: str, participants: list[str], judgment: str) -> str | None:
        """재촉 대상 결정 — 마지막 발화자가 아닌 사람"""
        recent = db.get_recent_messages(ch_name, limit=1)
        if not recent:
            return participants[0] if participants else None
        last_speaker = recent[-1]["speaker"]
        # 마지막 발화자가 아닌 사람에게 재촉
        for pid in participants:
            if pid != last_speaker:
                return pid
        return participants[0] if participants else None

    def _get_idle_seconds(self, channel: str) -> float:
        recent = db.get_recent_messages(channel, limit=1)
        if not recent:
            return 999
        try:
            last_dt = datetime.fromisoformat(recent[-1]["timestamp"])
            return (datetime.now() - last_dt).total_seconds()
        except Exception:
            return 999

    async def _inject_and_send(self, agent_id, ch_name, channel, instruction):
        """에이전트에게 강제 지시 주입"""
        # 에이전트가 이미 추론/전송 중이면 스킵
        if log_writer.is_thinking(agent_id) or log_writer.is_speaking(agent_id):
            return

        from src.bot import _get_channel_lock
        lock = _get_channel_lock(ch_name)
        if lock.locked():
            return

        async with lock:
            loop = asyncio.get_event_loop()
            responses = await loop.run_in_executor(
                None,
                lambda: runtime.generate_response_force(agent_id, ch_name, instruction)
            )
            cmd_pat = _re.compile(r'\[(?:CMD|QUERY|ACTION):[^\]]*\]')
            for resp in responses:
                clean = cmd_pat.sub('', resp).strip()
                if clean and clean != "..." and clean != "(무시)":
                    for part in _split_for_chat(clean):
                        await send_as_agent(channel, agent_id, part)
                        await asyncio.sleep(0.1)
                        # DB 로깅은 generate_response_force에서 이미 처리


# ── 감시자 레지스트리 + 루프 ────────────────────────────

SUPERVISORS: list[Supervisor] = [
    OnboardingSupervisor(),
    ChannelConversationSupervisor(),
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


_notify_idle_tasks: dict[str, asyncio.Task] = {}  # 채널별 대기 태스크 (중복 방지)


async def notify_idle(channel_name: str):
    """에이전트 응답 완료 후 호출 — 일정 시간 후 유저 응답 없으면 감시자 실행"""
    if not _active:
        return

    # 관련 채널인지 체크
    relevant = channel_name in (MGR_CHANNEL, CREATOR_CHANNEL) or channel_name.startswith("internal-")
    if not relevant:
        return

    # 이전 대기 태스크 취소 (같은 채널에서 연속 호출 시 중복 방지)
    prev = _notify_idle_tasks.get(channel_name)
    if prev and not prev.done():
        prev.cancel()

    async def _delayed_check():
        await asyncio.sleep(15)  # 15초 대기 — 유저 응답 기다림

        # 대기 후에도 마지막 메시지가 에이전트 것이면 (유저가 응답 안 함) → 체크
        recent = db.get_recent_messages(channel_name, limit=1)
        if recent:
            from src.core.profile import get_user_id
            last_speaker = recent[-1]["speaker"]
            if last_speaker != get_user_id():
                await _run_checks()

    _notify_idle_tasks[channel_name] = asyncio.create_task(_delayed_check())


def start_supervisors():
    """필요한 감시자 활성화"""
    global _active
    _active = [s for s in SUPERVISORS if s.should_run()]
    if _active:
        names = [s.name for s in _active]
        log_writer.system(f"[supervisor] 활성화: {', '.join(names)}")
    else:
        log_writer.system("[supervisor] 활성화할 감시자 없음")
