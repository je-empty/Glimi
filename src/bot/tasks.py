"""
Project Glimi — Background Tasks, Events & Error Handling

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
    bot, log, MGR_CHANNEL, MGR_SYSTEM_LOG, CREATOR_CHANNEL, MGR_ID,
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
        log_writer.system(f"서버 연결: {guild.name}")
        log_writer.system("채널 초기화 중...")
        await ensure_channels(guild)
        log_writer.system("아바타 동기화 중...")
        await sync_avatars(guild)

    from src import db as _db
    first_run = not _db.get_meta("yuna_greeted")
    profiles = list_all_profiles()

    if first_run:
        # 초기: mgr/creator만 활성화 (페르소나는 온보딩 완료 후)
        mgr_profiles = [p for p in profiles if p.get("type") in ("mgr", "creator")]
        log_writer.system(f"에이전트 활성화 중... (관리자 {len(mgr_profiles)}명)")
        for i, p in enumerate(mgr_profiles, 1):
            name = p.get("name", p["id"])
            log_writer.system(f"  [{i}/{len(mgr_profiles)}] {name} ({p.get('type', '?')}) 활성화")
            runtime.activate_agent(p["id"])
    else:
        log_writer.system(f"에이전트 활성화 중... ({len(profiles)}명)")
        for i, p in enumerate(profiles, 1):
            name = p.get("name", p["id"])
            agent_type = p.get("type", "?")
            log_writer.system(f"  [{i}/{len(profiles)}] {name} ({agent_type}) 활성화")
            runtime.activate_agent(p["id"])

    log.info("Glimi 봇 준비 완료")
    log_writer.system("봇 준비 완료")
    log_writer.mark_bot_ready()

    try:
        # 온보딩 상태 검증 — 채널 기반 안전장치
        await _verify_onboarding_state(guild)

        # 오너 정보 없으면 디코에서 가져오기 + 유나가 추가 정보 요청
        await _check_owner_profile(guild)
    except Exception as e:
        log_writer.system(f"❌ 온보딩 오류: {type(e).__name__}: {e}")
        log.error(f"[Onboarding] {e}", exc_info=True)

    # Supervisor 시스템 시작
    from src.bot.supervisors import start_supervisors
    start_supervisors()

    # 유나 자율 감시 + 시스템 로그 동기화 시작
    try:
        if not yuna_watcher.is_running():
            yuna_watcher.start()
        if not system_log_sync.is_running():
            system_log_sync.start()
    except Exception as e:
        log_writer.system(f"❌ 태스크 시작 오류: {e}")

    # 개발 결과 체크 (재시작 후)
    try:
        await check_dev_results()
    except Exception as e:
        log.error(f"[Dev] 결과 체크 오류: {e}")


async def _verify_onboarding_state(guild):
    """온보딩 완료 상태 검증 — 채널 기반 안전장치.
    메타 플래그와 실제 채널 상태가 불일치하면 보정."""
    from src import db as _db

    phase = _db.get_meta("onboarding_phase")
    greeted = _db.get_meta("yuna_greeted")

    if not guild:
        return

    ch_names = {ch.name for ch in guild.text_channels}

    # 필수 채널 3개
    has_dashboard = MGR_CHANNEL in ch_names
    has_system_log = MGR_SYSTEM_LOG in ch_names
    has_creator = CREATOR_CHANNEL in ch_names
    # 하나-유나 internal-dm
    has_internal = any(
        n.startswith("internal-dm-") and ("유나" in n or "하나" in n)
        for n in ch_names
    )

    all_channels = has_dashboard and has_system_log and has_creator

    if phase == "complete":
        # 이미 완료 — 검증만
        if not all_channels:
            log_writer.system(f"[온보딩 검증] phase=complete이지만 채널 부족 — 채널 재생성 필요")
        return

    # DB에 대화 기록이 있으면 온보딩은 이미 지난 것
    conn = _db.get_conn()
    has_messages = conn.execute("SELECT 1 FROM conversations LIMIT 1").fetchone() is not None
    conn.close()

    if has_messages or all_channels:
        # 대화 기록 또는 채널이 있으면 온보딩 완료로 보정
        if phase != "complete":
            _db.set_meta("onboarding_phase", "complete")
            if not greeted:
                _db.set_meta("yuna_greeted", "1")
            log_writer.system("[온보딩 검증] 온보딩 완료 보정 (대화 기록/채널 존재)")
    elif greeted:
        log_writer.system(f"[온보딩 검증] greeted=1, phase={phase}, 채널: dashboard={has_dashboard} syslog={has_system_log} creator={has_creator}")


async def _check_owner_profile(guild):
    """오너 프로필 체크 — 첫 인사 + 누락 정보 요청"""
    from src import db
    from src.core.profile import get_user_name, get_user_id
    import json as _json

    log_writer.system("[Onboarding] 오너 프로필 체크 시작")

    if not guild:
        log_writer.system("[Onboarding] guild 없음 — 스킵")
        return

    # 이미 인사했는지 체크
    greeted = db.get_meta("yuna_greeted")
    log_writer.system(f"[Onboarding] yuna_greeted={greeted}")

    # 디코 서버 오너 찾기
    owner_member = guild.owner
    if not owner_member:
        for member in guild.members:
            if not member.bot:
                owner_member = member
                break
    if not owner_member:
        log_writer.system("[Onboarding] 오너 멤버 찾기 실패 — 스킵")
        return
    log_writer.system(f"[Onboarding] 오너: {owner_member.display_name} (#{owner_member.id})")

    # 유저 레코드 없으면 디코 정보로 자동 등록, 있으면 디코 ID 업데이트
    discord_id = str(owner_member.id)
    conn = db.get_conn()
    existing = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO users (id, name) VALUES (?, ?)",
            (discord_id, owner_member.display_name),
        )
        db.set_meta("active_user_id", discord_id)
        conn.commit()
        log_writer.system(f"오너 자동 등록: {owner_member.display_name} (#{discord_id})")
    else:
        # 위저드에서 만든 레코드에 디스코드 ID가 없으면 meta에 저장
        db.set_meta("discord_owner_id", discord_id)
    conn.close()

    # 유저 정보 로드
    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    log_writer.system(f"[Onboarding] mgr 채널 검색: '{MGR_CHANNEL}' → {'찾음' if mgr_ch else '없음'}")
    if not mgr_ch:
        # 채널 목록 로그
        ch_names = [ch.name for ch in guild.text_channels]
        log_writer.system(f"[Onboarding] 서버 채널 목록: {ch_names[:20]}")
        return

    conn = db.get_conn()
    user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    conn.close()
    user = dict(user) if user else {}

    name = user.get("name", owner_member.display_name)
    age = user.get("age", "?")
    pers = user.get("personality")
    if isinstance(pers, str):
        try:
            pers = _json.loads(pers)
        except Exception:
            pers = {}
    pers = pers or {}
    gender = pers.get("gender", "")
    nickname = pers.get("nickname", "")

    # 유나 이름
    from src.core.profile import load_profile as _lp
    _mgr_profile = _lp(MGR_ID)
    p_name = _mgr_profile["name"] if _mgr_profile else "Yuna"

    # 누락 필드 체크
    missing = []
    if not user.get("mbti"):
        missing.append("MBTI")
    if not user.get("background"):
        missing.append("직업/하는 일")
    if not user.get("enneagram"):
        missing.append("에니어그램(모르면 패스)")

    first_time = not db.get_meta("yuna_greeted")

    if not first_time:
        # 온보딩 끝난 서버 — 정보 누락은 대화 중에 자연스럽게 물어봄
        return

    info = f"이름:{name}, 나이:{age}, 성별:{gender}, 별칭:{nickname}"
    log_writer.system("온보딩 준비")
    log_writer.mark_onboarding()

    if first_time:
        missing_str = ', '.join(missing) if missing else ""
        owner_age = int(age) if str(age).isdigit() else None
        yuna_age = 18
        older = owner_age and owner_age > yuna_age
        nick_info = f"nickname={nickname}" if nickname else "no nickname"

        # 언어별 문화 힌트
        from src.community import get_language
        lang = get_language()
        if lang == "ko":
            name_hint = f"Don't use full name ({name}). For Korean names, drop the surname (e.g. 홍길동→길동). Be friendly."
            honorific_hint = (
                f"- {name} is {age} years old. {'Older than you — start with formal speech (존댓말).' if older else 'Similar age or unknown — start formal.'}\n"
                f"- You want to get closer. {'Ask if casual speech is okay. ' if older else ''}"
                f"{'Ask if you can call them 오빠 (older brother).' if older and gender == '남' else ''}\n"
                f"- Ask their preferred speech style (formal/casual). This is required."
            )
        else:
            name_hint = f"Use first name only from ({name}). Be friendly and casual."
            honorific_hint = (
                f"- Ask what they'd like to be called.\n"
                f"- Ask if they prefer casual or formal chat style."
            )

        prompt = (
            f"[Situation] New person just joined the community.\n"
            f"Their info: name={name}, {nick_info}, age={age}, gender={gender}\n"
            f"[Your situation] You ({p_name}, {yuna_age}y/o female) are the community's head manager.\n"
            f"This is your first time talking to them.\n"
            f"[Name rules]\n"
            f"- {name_hint}\n"
            f"- {('Their nickname is ' + nickname + '. Use it or their first name — your call.') if nickname else 'No nickname. You can suggest one or ask what to call them.'}\n"
            f"- NEVER use 'owner', 'user', or similar terms.\n"
            f"[Speech rules]\n"
            f"{honorific_hint}\n"
            f"- One question at a time.\n"
            f"- Don't mention your own age.\n"
            f"[Include]\n"
            f"- Self-introduction (name, role: managing agents and communication)\n"
            f"- What this place is (AI agents living together, forming relationships)\n"
            f"- Profile setup needed before chatting with agents\n"
            f"- Ask about preferred name/speech style\n"
            f"[Info to collect] MBTI, job, hobby — ask at least 2. Skip if they don't know.\n"
            f"{'Currently missing: ' + missing_str if missing else ''}\n"
            f"[Profile done] Once name/speech decided + 2+ questions asked → immediately send "
            f"[CMD:프로필수집완료]. If not sent, onboarding never ends.\n"
            f"[Style] Short chat messages, multiple lines. Natural and friendly. No robotic speech.\n"
            f"[Forbidden] No CMD/QUERY/ACTION tags except [CMD:프로필수집완료] in this first greeting."
        )

    log_writer.system("유나 불러오는 중...")
    await asyncio.sleep(3)
    loop = asyncio.get_event_loop()
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response(
            MGR_ID, MGR_CHANNEL, prompt, log_user_message=False
        )
    )
    log_writer.system("유나가 도착했어요!")
    import re as _re
    cmd_pattern = _re.compile(r'\[(?:CMD|QUERY|ACTION):[^\]]*\]')
    for resp in responses:
        # CMD/QUERY/ACTION 태그 제거
        resp = cmd_pattern.sub('', resp).strip()
        if not resp:
            continue
        for part in _split_for_chat(resp):
            await send_as_agent(mgr_ch, MGR_ID, part)
            await asyncio.sleep(1)

    if first_time:
        db.set_meta("yuna_greeted", "1")

    log_writer.system("온보딩 완료")
    log_writer.mark_onboarding_done()


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

    # 유나에게 활동 알림 — 특이사항만 보고, 일상 대화는 무시
    notify = "\n".join(new_events)
    notify_prompt = (
        f"[자동알림] 최근 활동:\n{notify}\n\n"
        f"이건 참고용이야. 대부분은 무시해도 돼.\n"
        f"정말 특이하거나 이상한 대화가 있을 때만 {get_user_name()}한테 말 걸어.\n"
        f"일상적인 대화면 아무것도 하지 마. 응답하지 마."
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
            # 빈 응답("...", 공백 등)은 유나가 안 보내기로 한 것
            if not resp or resp.strip() in ("", "...", "(무시)"):
                continue
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
