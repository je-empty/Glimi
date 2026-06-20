#!/usr/bin/env python3
"""
Project Glimi — Discord Bot (Entry Point)

에이전트들과 디스코드에서 대화하는 중계 봇

실행: python -m community.discord_bot
환경변수: DISCORD_BOT_TOKEN (또는 .env 파일)
"""
import json
import os
import signal
import sys
from pathlib import Path

from community import db, community
from community.core.profile import register_all_to_db, setup_initial_relationships

# bot 패키지에서 공유 상태 + bot 인스턴스 로드
from community.bot import bot, TOKEN, CHANNEL_AGENT_MAP, log
import community.bot as _bot_state
from community.bot.core import _build_channel_maps

# 하위 모듈 임포트 — 데코레이터(@bot.event, @bot.command, @tasks.loop) 등록
import community.bot.handlers    # noqa: F401 — on_message
import community.bot.commands    # noqa: F401 — !commands
import community.bot.tasks       # noqa: F401 — background tasks + events

# 도전과제 엔진 — db.log_message 훅으로 진척도 자동 추적
from community.achievements import engine as _ach_engine
_ach_engine.install()

# 메모리 시스템 — 오너 발화도 추출 대상에 포함 (오너 관점 memories 누적)
from community.core.memory import install_owner_extraction_hook as _install_mem_hook
_install_mem_hook()


def _kill_existing_bot():
    """같은 커뮤니티의 기존 봇 프로세스 종료"""
    pid_dir = Path(__file__).parent.parent / "dev"
    pid_dir.mkdir(exist_ok=True)
    cid = community.get_community_id()

    # 커뮤니티별 PID 파일
    pid_file = pid_dir / f".bot-{cid}.pid"
    general_pid = pid_dir / ".bot.pid"

    for pf in [pid_file, general_pid]:
        if pf.exists():
            try:
                old_pid = int(pf.read_text().strip())
                if old_pid != os.getpid():
                    os.kill(old_pid, signal.SIGTERM)
                    log.info(f"기존 봇 종료 (PID {old_pid})")
                    import time
                    time.sleep(1)
            except (ProcessLookupError, ValueError):
                pass
            pf.unlink(missing_ok=True)

    # 현재 PID 기록
    pid_file.write_text(str(os.getpid()))
    general_pid.write_text(str(os.getpid()))


def main():
    cid = community.get_community_id()
    community.set_community(cid)  # 언어 등 커뮤니티 컨텍스트 초기화
    # budget guard 용 active community 전파 (이 봇 프로세스는 단일 커뮤니티).
    try:
        from community.core import runtime as _rt
        _rt.set_active_community(cid)
    except Exception:
        pass
    log.info(f"커뮤니티: {cid} ({community.get_community_dir()})")

    _kill_existing_bot()

    # stale thinking/speaking flag 정리 — 옛 봇이 응답 중 크래시 시 잔존하면 영구 thinking 으로 인식.
    try:
        from community import log_writer
        n = log_writer.clear_runtime_flags()
        if n:
            log.info(f"stale runtime flags 정리: {n}건")
    except Exception as e:
        log.warning(f"runtime flag 정리 실패 (무시): {e}")

    if not TOKEN:
        env_path = community.get_env_path()
        print()
        print("=" * 55)
        print("  DISCORD_BOT_TOKEN is not set.")
        print()
        print(f"  Check the .env file for server '{cid}':")
        print(f"    {env_path}")
        print()
        print("  Or initialize a new server:")
        print(f"    python -m community.community init {cid}")
        print("=" * 55)
        sys.exit(1)

    db.init_db()

    # 에이전트가 없으면 mgr(유나) 만 시드.
    # 크리에이터(하나) 는 튜토리얼 channels_setup phase 에 lazy 등록 —
    # 오너 시점에 "튜토리얼 중 하나가 새로 생기는 것처럼" 보이게.
    if not db.list_agents():
        seed_path = Path(__file__).parent.parent / "assets" / "seed_agents.json"
        if seed_path.exists():
            log.info("기본 에이전트 시드 (mgr 만) 적용 중...")
            with open(seed_path, "r", encoding="utf-8") as f:
                seeds = json.load(f)
            seeded = 0
            for agent in seeds:
                if agent.get("type") == "mgr":
                    db.save_agent_profile(agent)
                    seeded += 1
            log.info(f"시드 에이전트 {seeded}개 등록 완료 (creator 는 튜토리얼 중 lazy 등록)")

    register_all_to_db()
    setup_initial_relationships()

    _build_channel_maps()
    log.info(f"채널 매핑: {CHANNEL_AGENT_MAP}")

    try:
        bot.run(TOKEN)
    except Exception as e:
        from community import log_writer
        log_writer.system(f"Bot login failed: {type(e).__name__}: {e}")
        print(f"\n  Bot login failed: {e}")
        print(f"  Check your token in: {community.get_env_path()}")
        sys.exit(1)

    # 봇 종료 후 — 개발 요청이면 exit(42)
    if _bot_state._shutdown_pending:
        log.info("[Dev] exit(42) — run.sh가 dev_runner 실행 예정")
        sys.exit(42)


if __name__ == "__main__":
    main()
