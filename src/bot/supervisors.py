"""
Project Glimi — Supervisor 시스템

에이전트 뒤에서 동작하는 감시자들. 유저/에이전트에게 보이지 않음.
각 Supervisor는 특정 조건을 감시하고, 필요시 에이전트에게 내부 프롬프트를 주입.

씬별 감시자는 `src/scenes/{scene_id}/supervisor.py` 에 정의하고, 여기서 수집한다.
이 파일은 범용 ChannelConversationSupervisor 등 씬 비의존 감시자만 유지.
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


# ── 온보딩 감시자 (scenes/onboarding/supervisor.py로 이전) ────────────
# 씬 전용 감시자는 각 씬 모듈에서 관리. SUPERVISORS 리스트에서만 참조.
from src.scenes.onboarding import scene as _onboarding_scene
from src.scenes.onboarding.supervisor import OnboardingSupervisor  # noqa: E402


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
            # SQLite CURRENT_TIMESTAMP는 UTC. utcnow로 비교해야 시간대 mismatch 안 남.
            return (datetime.utcnow() - last_dt).total_seconds()
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

def _build_supervisor_list() -> list[Supervisor]:
    """모든 감시자 수집 — 등록된 모든 scene의 supervisor + 씬 비의존 범용 감시자."""
    from src.scenes import all_scenes
    result: list[Supervisor] = []
    for s in all_scenes():
        sup = s.supervisor()
        if sup is not None:
            result.append(sup)
    result.append(ChannelConversationSupervisor())
    return result


SUPERVISORS: list[Supervisor] = _build_supervisor_list()

_active: list[Supervisor] = []
_pending_check: asyncio.Event | None = None


async def _run_checks():
    """활성 감시자 체크 실행"""
    from src.bot.core import get_target_guild
    guild = get_target_guild()
    if not guild:
        return

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
