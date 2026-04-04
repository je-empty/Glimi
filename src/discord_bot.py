#!/usr/bin/env python3
"""
Project Chaos — Discord Bot (Entry Point)

에이전트들과 디스코드에서 대화하는 중계 봇

실행: python -m src.discord_bot
환경변수: DISCORD_BOT_TOKEN (또는 .env 파일)
"""
import json
import os
import signal
import sys
from pathlib import Path

from src import db, community
from src.core.profile import register_all_to_db, setup_initial_relationships

# bot 패키지에서 공유 상태 + bot 인스턴스 로드
from src.bot import bot, TOKEN, CHANNEL_AGENT_MAP, log
import src.bot as _bot_state
from src.bot.core import _build_channel_maps

# 하위 모듈 임포트 — 데코레이터(@bot.event, @bot.command, @tasks.loop) 등록
import src.bot.handlers    # noqa: F401 — on_message
import src.bot.commands    # noqa: F401 — !commands
import src.bot.tasks       # noqa: F401 — background tasks + events


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
    log.info(f"커뮤니티: {cid} ({community.get_community_dir()})")

    _kill_existing_bot()

    if not TOKEN:
        env_path = community.get_env_path()
        print()
        print("=" * 55)
        print("  DISCORD_BOT_TOKEN이 설정되지 않았습니다.")
        print()
        print(f"  커뮤니티 '{cid}'의 .env 파일을 확인하세요:")
        print(f"    {env_path}")
        print()
        print("  또는 새 커뮤니티 초기화:")
        print(f"    python -m src.community init {cid}")
        print("=" * 55)
        sys.exit(1)

    db.init_db()

    # 에이전트가 없으면 시드 데이터 자동 적용
    if not db.list_agents():
        seed_path = Path(__file__).parent.parent / "assets" / "seed_agents.json"
        if seed_path.exists():
            log.info("기본 에이전트 시드 적용 중...")
            with open(seed_path, "r", encoding="utf-8") as f:
                seeds = json.load(f)
            for agent in seeds:
                db.save_agent_profile(agent)
            log.info(f"시드 에이전트 {len(seeds)}개 등록 완료")

    register_all_to_db()
    setup_initial_relationships()

    _build_channel_maps()
    log.info(f"채널 매핑: {CHANNEL_AGENT_MAP}")

    bot.run(TOKEN)

    # 봇 종료 후 — 개발 요청이면 exit(42)
    if _bot_state._shutdown_pending:
        log.info("[Dev] exit(42) — run.sh가 dev_runner 실행 예정")
        sys.exit(42)


if __name__ == "__main__":
    main()
