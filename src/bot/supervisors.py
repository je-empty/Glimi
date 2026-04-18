"""
Project Glimi — Supervisor 모듈 shim

실제 supervisor 로직은 `src/supervisors/` 패키지로 이전됨:
- src/supervisors/base.py       : Supervisor 베이스 + SupervisorPool (singleton `pool`)
- src/supervisors/chat.py       : ChatSupervisor (channel, 1:1 per running)
- src/supervisors/orchestrator.py : OrchestratorSupervisor (system, singleton)
- src/scenes/<scene_id>/supervisor.py : scene-scoped (예: OnboardingFlowSupervisor)

이 파일은 기존 호출부(start_supervisors, notify_idle, _run_checks)가
계속 동작하도록 얇은 wrapper만 제공.
"""
import asyncio

from src import db, log_writer
from src.bot import MGR_CHANNEL, CREATOR_CHANNEL
# 씬 모듈 import해서 레지스트리에 등록되게 함 (부작용)
from src.scenes.onboarding import scene as _onboarding_scene  # noqa: F401



# ── Pool 연결 (실제 supervisor 로직은 src/supervisors/base.py 의 pool 이 관리) ──

_notify_idle_tasks: dict[str, asyncio.Task] = {}  # 채널별 대기 태스크 (중복 방지)


async def _run_checks():
    """pool.tick() 위임. 기존 호출부(notify_idle 등)가 쓰던 진입점 유지."""
    from src.bot.core import get_target_guild
    from src.supervisors.base import pool
    guild = get_target_guild()
    if not guild:
        return
    await pool.tick(guild)


async def notify_idle(channel_name: str):
    """에이전트 응답 완료 후 호출 — 일정 시간 후 유저 응답 없으면 pool tick 실행"""
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
        recent = db.get_recent_messages(channel_name, limit=1)
        if recent:
            from src.core.profile import get_user_id
            last_speaker = recent[-1]["speaker"]
            if last_speaker != get_user_id():
                await _run_checks()

    _notify_idle_tasks[channel_name] = asyncio.create_task(_delayed_check())


def start_supervisors():
    """봇 ready 시 호출: system supervisors 등록 + 최초 sync."""
    from src.supervisors.base import pool
    pool.register_system_supervisors()

    # 초기 scene/channel sync는 별도 태스크로 (지금 시점엔 이벤트 루프 안)
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
        # 이벤트 루프 없으면 그냥 무시 (봇 아직 안 뜸)
        pass
