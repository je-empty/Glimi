"""
Project Chaos — Background Tasks, Events & Error Handling

discord_bot.py에서 분리:
- on_disconnect / on_resumed / on_ready 이벤트
- yuna_watcher (5분 루프) + system_log_sync (10초 루프)
- 런타임 에러 자동 감지 + 보고 + 개발 요청
"""
import os
import asyncio
import random
import traceback as _tb
from datetime import datetime

import discord
from discord.ext import tasks

from src import db
from src import log_writer
from src.core.profile import list_all_profiles, get_user_name, get_user_id
from src.core.runtime import runtime
from src.bot import (
    bot, log, MGR_CHANNEL, MGR_SYSTEM_LOG, MGR_ID,
    _webhook_cache, _last_activity_snapshot,
    DAILY_SOCIAL_LIMIT,
    _last_log_line_count, _runtime_error_counts,
    _runtime_error_reported, AUTO_DEV_REQUEST_THRESHOLD,
)
import src.bot as _bot_state  # for modifying module-level primitives
from src.bot.core import (
    send_as_agent, _split_for_chat, ensure_channels, sync_avatars,
)
from src.bot.mgr_system import (
    parse_and_execute_actions, check_dev_results, yuna_dev_request,
)


# ── 이벤트 핸들러 ─────────────────────────────────────

@bot.event
async def on_disconnect():
    log.warning("🔴 디스코드 게이트웨이 연결 끊김")
    log_writer.system("🔴 디스코드 게이트웨이 연결 끊김")


@bot.event
async def on_resumed():
    log.info("🟢 디스코드 게이트웨이 재연결 완료")
    log_writer.system("🟢 디스코드 게이트웨이 재연결 완료")
    # 재연결 시 webhook 캐시 클리어 (만료됐을 수 있음)
    _webhook_cache.clear()


@bot.event
async def on_ready():
    log.info(f"🟢 봇 로그인: {bot.user.name}")
    log_writer.system(f"봇 로그인: {bot.user.name}")

    if bot.guilds:
        guild = bot.guilds[0]
        log.info(f"서버: {guild.name}")
        await ensure_channels(guild)
        await sync_avatars(guild)

    for p in list_all_profiles():
        runtime.activate_agent(p["id"])

    log.info("Chaos 봇 준비 완료")
    log_writer.system("봇 준비 완료")

    # 유나 자율 감시 + 시스템 로그 동기화 시작
    if not yuna_watcher.is_running():
        yuna_watcher.start()
    if not system_log_sync.is_running():
        system_log_sync.start()

    # 개발 결과 체크 (재시작 후)
    try:
        await check_dev_results()
    except Exception as e:
        log.error(f"[Dev] 결과 체크 오류: {e}")


# ── 유나 자율 감시 + 소셜 펄스 ─────────────────────────

@tasks.loop(minutes=5)
async def yuna_watcher():
    """5분마다: 활동 감지 + 유나 판단으로 자율 대화 트리거"""

    if not bot.guilds:
        return

    guild = bot.guilds[0]
    mgr_channel = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    if not mgr_channel:
        return

    # 날짜 변경 시 예산 리셋
    today = datetime.now().strftime("%Y-%m-%d")
    if today != _bot_state._daily_social_date:
        _bot_state._daily_social_count = 0
        _bot_state._daily_social_date = today

    overview = db.get_channel_overview()
    new_events = []

    for ch in overview:
        ch_name = ch["channel"]
        if ch_name.startswith("mgr"):
            continue
        cur_count = ch["msg_count"]
        prev_count = _last_activity_snapshot.get(ch_name, cur_count)

        if cur_count > prev_count:
            diff = cur_count - prev_count
            recent = db.get_recent_messages(ch_name, limit=1)
            if recent:
                r = recent[0]
                speaker = get_user_name() if r["speaker"] == get_user_id() else runtime.get_agent_name(r["speaker"])
                preview = r["message"][:40]
                new_events.append(f"{ch_name}에서 {diff}건 새 대화 ({speaker}: \"{preview}\")")

        _last_activity_snapshot[ch_name] = cur_count

    if not new_events:
        return

    # 유나에게 활동 보고만 (대화 시작은 오빠가 시킬 때만)
    notify = "\n".join(new_events)
    notify_prompt = (
        f"[자동알림] 최근 활동:\n{notify}\n\n"
        f"특이사항 있으면 오빠한테 보고. 별거 아니면 가볍게 한마디만 하거나 안 해도 됨."
    )

    try:
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(
                MGR_ID, MGR_CHANNEL, notify_prompt, log_user_message=False
            )
        )
        if responses and guild:
            responses = await parse_and_execute_actions(mgr_channel, responses, guild)
        for resp in responses:
            for part in _split_for_chat(resp):
                await send_as_agent(mgr_channel, MGR_ID, part)
                await asyncio.sleep(0.3 + random.uniform(0, 0.4))
    except Exception as e:
        log.error(f"[유나감시] 오류: {e}")


@yuna_watcher.before_loop
async def before_yuna_watcher():
    await bot.wait_until_ready()
    for ch in db.get_channel_overview():
        _last_activity_snapshot[ch["channel"]] = ch["msg_count"]


# ── 시스템 로그 → 디코 동기화 ─────────────────────────

def _count_log_lines():
    log_path = os.path.join(log_writer.get_log_dir(), "system.log")
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0


@tasks.loop(seconds=10)
async def system_log_sync():
    """시스템 로그 새 줄을 mgr-system-log 디코 채널에 전송"""
    if not bot.guilds:
        return
    guild = bot.guilds[0]
    ch = discord.utils.get(guild.text_channels, name=MGR_SYSTEM_LOG)
    if not ch:
        return

    total = _count_log_lines()
    if total <= _bot_state._last_log_line_count:
        return

    new_count = total - _bot_state._last_log_line_count
    new_lines = log_writer.tail(os.path.join(log_writer.get_log_dir(), "system.log"), new_count)

    # ACTION + 크리티컬 에러만 필터
    important = [l for l in new_lines if any(k in l for k in (
        "🔔 ACTION", "✓ ACTION", "❌", "강제지시", "봇 시작", "봇 종료", "🔧",
    ))]
    if important:
        try:
            await ch.send("```\n" + "\n".join(important) + "\n```")
        except Exception:
            pass

    _bot_state._last_log_line_count = total


@system_log_sync.before_loop
async def before_system_log_sync():
    await bot.wait_until_ready()
    _bot_state._last_log_line_count = _count_log_lines()


# ── 런타임 에러 자동 감지 + 보고 + 개발 요청 ─────────

def _error_key(e: Exception) -> str:
    """에러 유형 + 발생 위치 기반 키 (같은 에러 추적용)"""
    tb = _tb.extract_tb(e.__traceback__)
    location = f"{tb[-1].filename}:{tb[-1].lineno}" if tb else "unknown"
    return f"{type(e).__name__}@{location}"


async def _handle_runtime_error(guild, channel_name: str, e: Exception):
    """런타임 에러 발생 시: 유나 보고 + 반복 시 자동 개발 요청"""
    if not guild:
        return

    err_key = _error_key(e)
    _runtime_error_counts[err_key] = _runtime_error_counts.get(err_key, 0) + 1
    count = _runtime_error_counts[err_key]

    # 에러 요약
    tb_lines = _tb.format_exception(type(e), e, e.__traceback__)
    tb_short = "".join(tb_lines[-3:])[:300]
    error_summary = f"{type(e).__name__}: {str(e)[:100]}"

    # 1) 유나가 오빠한테 보고 (매번)
    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    if mgr_ch:
        report = (
            f"⚠️ 런타임 오류 발생 ({count}회째)\n"
            f"채널: {channel_name}\n"
            f"에러: {error_summary}\n"
        )
        if count >= AUTO_DEV_REQUEST_THRESHOLD and err_key not in _runtime_error_reported:
            report += "→ 같은 에러 반복이라 자동으로 개발 요청 넣을게!"
        try:
            await send_as_agent(mgr_ch, MGR_ID, report)
        except Exception:
            pass

    # 2) 같은 에러 N회 반복 → 자동 개발 요청
    if count >= AUTO_DEV_REQUEST_THRESHOLD and err_key not in _runtime_error_reported:
        _runtime_error_reported.add(err_key)

        if _bot_state._shutdown_pending:
            return

        dev_desc = (
            f"[자동 버그 리포트] 런타임 에러 {count}회 반복 발생\n"
            f"채널: {channel_name}\n"
            f"에러: {error_summary}\n"
            f"트레이스백:\n{tb_short}\n\n"
            f"이 에러가 반복적으로 발생하고 있음. 원인 파악 후 수정 필요."
        )

        try:
            await yuna_dev_request(mgr_ch, dev_desc, "시스템(자동감지)")
        except Exception as dev_err:
            log.error(f"[AutoDev] 자동 개발 요청 실패: {dev_err}")
