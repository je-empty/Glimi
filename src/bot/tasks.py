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
from src.i18n import t
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
    send_as_agent, _split_for_chat, ensure_channels, sync_profile_images,
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

    # Tool handlers 등록 (registry에 handler 주입)
    try:
        from src.bot.tool_handlers import register_all as _register_tools
        _register_tools()
        from src.glimi.tools import TOOLS as _TOOLS
        log_writer.system(f"Tools registered: {len(_TOOLS)}")
    except Exception as e:
        log_writer.system(f"❌ Tool registration failed: {e}")

    if bot.guilds:
        # DISCORD_GUILD_ID 기준으로 타겟 guild 선택. 미매칭이면 더 진행하지 않고 fail-fast
        # (다른 서버에 메시지 쓰는 사고 방지)
        from src.bot.core import get_target_guild
        guild = get_target_guild()
        if not guild:
            log_writer.system("❌ 타겟 guild 확정 불가 — 봇 초기화 중단")
            return
        # GUILD_ID 가 .env 에 없는 신규 커뮤니티면 자동 persist (next boot 부터 명시적 사용)
        if not os.environ.get("DISCORD_GUILD_ID"):
            try:
                from dotenv import set_key
                from src import community as _comm
                env_path = _comm.get_env_path()
                set_key(env_path, "DISCORD_GUILD_ID", str(guild.id), quote_mode="never")
                os.environ["DISCORD_GUILD_ID"] = str(guild.id)
                log_writer.system(
                    f"[startup] DISCORD_GUILD_ID 자동 감지: {guild.id} ({guild.name}) → .env 저장"
                )
            except Exception as e:
                log_writer.system(f"[startup] guild_id .env 저장 실패: {e}")
        log.info(f"서버: {guild.name}")
        log_writer.system(f"Server connected: {guild.name}")
        log_writer.system("Initializing channels...")
        await ensure_channels(guild)
        # 채널 순서 정렬 — 카테고리 순서 + 각 카테고리 내부 규칙. 봇이 이미 연결돼 있으니
        # 자체 Discord client 열 필요 없이 guild 객체 그대로 사용.
        try:
            from src.core.sync import arrange_with_guild
            await arrange_with_guild(guild)
        except Exception as e:
            log_writer.system(f"⚠ 채널 정렬 실패 (무시하고 진행): {e}")
        log_writer.system("Syncing profile images...")
        await sync_profile_images(guild)

    from src import db as _db
    first_run = not _db.get_meta("yuna_greeted")
    profiles = list_all_profiles()

    if first_run:
        # 초기: mgr/creator만 활성화 (페르소나는 튜토리얼 완료 후)
        mgr_profiles = [p for p in profiles if p.get("type") in ("mgr", "creator")]
        log_writer.system(f"Activating agents... (managers {len(mgr_profiles)}명)")
        for i, p in enumerate(mgr_profiles, 1):
            name = p.get("name", p["id"])
            log_writer.system(f"  [{i}/{len(mgr_profiles)}] {name} ({p.get('type', '?')}) 활성화")
            runtime.activate_agent(p["id"])
    else:
        log_writer.system(f"Activating agents... ({len(profiles)}명)")
        for i, p in enumerate(profiles, 1):
            name = p.get("name", p["id"])
            agent_type = p.get("type", "?")
            log_writer.system(f"  [{i}/{len(profiles)}] {name} ({agent_type}) 활성화")
            runtime.activate_agent(p["id"])

    # 한세나 (dev) 모든 커뮤니티 봇 시작 시 자동 시드. 가시성은 별개 (가시성 필터가
    # 일반 커뮤니티 + 비-admin 한테 자동 숨김 처리). DB 에 항상 존재해야 첫 request_dev_fix
    # 호출 시 race 없이 즉시 invoke 가능.
    try:
        from src.core.dev_agent import ensure_dev_seeded
        if ensure_dev_seeded():
            log_writer.system("[startup] 한세나 (dev) auto-seeded")
    except Exception as _e:
        log_writer.system(f"[startup] dev auto-seed 실패 (skip): {_e}")

    # 매니저류 (mgr/creator/dev) 와 오너 사이 관계 row 가 없으면 default 로 생성.
    # 이전엔 합성 (synthetic) row 만 API 응답에 끼워넣어서 dynamics 가 고정 텍스트였음.
    # 실제 row 가 있어야 L1 메모리 분석기가 대화 보고 dynamics / intimacy 를 동적으로 업데이트.
    try:
        from src.core.profile import get_user_id
        owner_id = get_user_id()
        if owner_id:
            seed_rels = [
                ("agent-mgr-001",     "매니저",     "매니저 — 커뮤니티 운영 도와줌"),
                ("agent-creator-001", "크리에이터", "크리에이터 — 친구 만들어주는 역할"),
                ("agent-dev-001",     "개발 담당",  "개발 담당 — 시스템 이슈 처리"),
            ]
            for aid, rtype, rdyn in seed_rels:
                if not db.get_agent(aid):
                    continue
                existing = db.get_relationship(owner_id, aid) or db.get_relationship(aid, owner_id)
                if not existing:
                    db.add_relationship(owner_id, aid, rtype, intimacy=db.INTIMACY_SCALE_DEFAULT, dynamics=rdyn)
                    log_writer.system(f"[startup] 매니저류 관계 시드: {aid} ({rtype})")
    except Exception as _e:
        log_writer.system(f"[startup] 매니저 관계 시드 실패 (skip): {_e}")

    log.info("Glimi Bot ready")
    log_writer.system("Bot ready")
    log_writer.mark_bot_ready()

    # 백로그 catch-up — 모든 활성 (agent, channel) 페어를 추출 큐에 enqueue.
    # 워커 풀이 drain mode 로 백로그 흡수. 라이브 freshness 회복.
    try:
        from src.core.memory import enqueue_extraction
        from src import db as _db
        # 각 에이전트의 주 채널
        for p in profiles:
            atype = p.get("type", "persona")
            name = p.get("name", "")
            if atype == "mgr":
                ch = "mgr-dashboard"
            elif atype == "creator":
                ch = "mgr-creator"
            else:
                ch = f"dm-{name}"
            enqueue_extraction(p["id"], ch)
        # 오너 관점 메모리도 — 모든 dm/mgr 채널의 오너 발화
        from src.core.profile import get_user_id
        oid = get_user_id()
        if oid:
            conn = _db.get_conn()
            chs = [r[0] for r in conn.execute(
                "SELECT DISTINCT channel FROM conversations WHERE speaker=? AND "
                "(channel LIKE 'dm-%' OR channel LIKE 'mgr-%' OR channel LIKE 'group-%')",
                (oid,),
            ).fetchall()]
            conn.close()
            for ch in chs:
                enqueue_extraction(oid, ch)
        log_writer.system(f"[Memory] startup catch-up enqueued: {len(profiles)} agents + 오너 채널들")
    except Exception as e:
        log_writer.system(f"[Memory] startup enqueue 실패 (무시): {e}")

    try:
        # 튜토리얼 상태 검증 — 채널 기반 안전장치
        await _verify_tutorial_state(guild)

        # Hana 첫 인사 누락 복구 (NameError 등 abort 회귀 시) — phase 가 channels_done/complete
        # 인데 mgr-creator 에 creator 발화 0 건이면 강제 재발사.
        try:
            from src.scenes.tutorial.handlers import force_hana_greeting_if_missing
            await force_hana_greeting_if_missing(guild)
        except Exception as _e:
            log_writer.system(f"[recovery] Hana 인사 복구 시도 실패: {_e}")

        # 오너 정보 없으면 디코에서 가져오기 + 유나가 추가 정보 요청
        await _check_owner_profile(guild)
    except Exception as e:
        log_writer.system(f"❌ 튜토리얼 오류: {type(e).__name__}: {e}")
        log.error(f"[Tutorial] {e}", exc_info=True)

    # Supervisor 시스템 시작
    from src.bot.supervisors import start_supervisors
    start_supervisors()

    # 유나 자율 감시 + 시스템 로그 동기화 시작
    try:
        if not yuna_watcher.is_running():
            yuna_watcher.start()
        if not system_log_sync.is_running():
            system_log_sync.start()
        if not alive_heartbeat.is_running():
            alive_heartbeat.start()
        if not supervisor_tick.is_running():
            supervisor_tick.start()
    except Exception as e:
        log_writer.system(f"❌ 태스크 시작 오류: {e}")

    # 개발 결과 체크 (재시작 후)
    try:
        await check_dev_results()
    except Exception as e:
        log.error(f"[Dev] 결과 체크 오류: {e}")


async def _verify_tutorial_state(guild):
    """튜토리얼 완료 상태 검증 — 채널 기반 안전장치.
    메타 플래그와 실제 채널 상태가 불일치하면 보정."""
    from src import db as _db

    phase = _db.get_meta("tutorial_phase")
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
            log_writer.system(f"[튜토리얼 검증] phase=complete이지만 채널 부족 — 채널 재생성 필요")
        return

    if all_channels:
        # 필수 채널 3개(dashboard/system_log/creator) 가 모두 존재하면 Phase 2 이상 진행됐다는
        # 실질 증거 → 완료로 보정. "대화 기록" 존재는 Phase 1 프로필 수집 중에도 쌓이기 때문에
        # 지표로 쓰면 진행 중인 튜토리얼을 잘못 complete 로 마킹해 Phase 2 진입을 영구 차단.
        if phase != "complete":
            _db.set_meta("tutorial_phase", "complete")
            if not greeted:
                _db.set_meta("yuna_greeted", "1")
            log_writer.system("[튜토리얼 검증] 튜토리얼 완료 보정 (필수 채널 모두 존재)")
    elif greeted:
        log_writer.system(f"[튜토리얼 검증] greeted=1, phase={phase}, 채널: dashboard={has_dashboard} syslog={has_system_log} creator={has_creator}")


async def _check_owner_profile(guild):
    """오너 프로필 체크 — 첫 인사 + 누락 정보 요청"""
    from src import db
    from src.core.profile import get_user_name, get_user_id
    import json as _json

    log_writer.system("[Tutorial] Checking owner profile")

    if not guild:
        log_writer.system("[Tutorial] guild 없음 — 스킵")
        return

    # 이미 인사했는지 체크
    greeted = db.get_meta("yuna_greeted")
    log_writer.system(f"[Tutorial] yuna_greeted={greeted}")

    # 디코 서버 오너 찾기
    owner_member = guild.owner
    if not owner_member:
        for member in guild.members:
            if not member.bot:
                owner_member = member
                break
    if not owner_member:
        log_writer.system("[Tutorial] Owner member not found — skip")
        return
    log_writer.system(f"[Tutorial] 오너: {owner_member.display_name} (#{owner_member.id})")

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
        log_writer.system(f"Owner auto-registered: {owner_member.display_name} (#{discord_id})")
    else:
        # 위저드에서 만든 레코드에 디스코드 ID가 없으면 meta에 저장
        db.set_meta("discord_owner_id", discord_id)
    conn.close()

    # 유저 정보 로드
    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    log_writer.system(f"[Tutorial] mgr 채널 검색: '{MGR_CHANNEL}' → {'찾음' if mgr_ch else '없음'}")
    if not mgr_ch:
        # 채널 목록 로그
        ch_names = [ch.name for ch in guild.text_channels]
        log_writer.system(f"[Tutorial] 서버 채널 목록: {ch_names[:20]}")
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
        # 튜토리얼 끝난 서버 — 정보 누락은 대화 중에 자연스럽게 물어봄
        return

    info = f"이름:{name}, 나이:{age}, 성별:{gender}, 별칭:{nickname}"
    log_writer.system(t("tutorial.prep"))
    log_writer.mark_tutorial()

    if first_time:
        owner_age = int(age) if str(age).isdigit() else None
        yuna_age = 18
        older = bool(owner_age and owner_age > yuna_age)
        from src.community import get_language
        from src.scenes.tutorial.greeting import build_yuna_greeting_prompt
        prompt = build_yuna_greeting_prompt(
            name=name,
            age=age,
            gender=gender,
            nickname=nickname,
            missing=missing,
            p_name=p_name,
            yuna_age=yuna_age,
            older=older,
            lang=get_language(),
        )

    log_writer.system(t("tutorial.yuna_loading"))
    await asyncio.sleep(3)
    loop = asyncio.get_event_loop()
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response(
            MGR_ID, MGR_CHANNEL, prompt, log_user_message=False
        )
    )
    log_writer.system(t("tutorial.yuna_arrived"))
    for resp in responses:
        resp = resp.strip()
        if not resp:
            continue
        for part in _split_for_chat(resp):
            await send_as_agent(mgr_ch, MGR_ID, part)
            await asyncio.sleep(1)

    if first_time:
        db.set_meta("yuna_greeted", "1")

    log_writer.system("유나 첫 인사 완료")  # scene=tutorial complete 아님 (그건 finish_tutorial tool 시)
    log_writer.mark_tutorial_done()


# ── 봇 alive heartbeat ──────────────────────────────────
#   대시보드는 system.log mtime 기반으로 봇 alive 판정 (120초 임계).
#   봇이 응답 생성으로 오래 묶여서 로그 미발생 시 false offline 처리되는 걸 방지.

@tasks.loop(seconds=45)
async def alive_heartbeat():
    try:
        path = os.path.join(log_writer.get_log_dir(), "system.log")
        if not os.path.exists(path):
            open(path, "a").close()
        os.utime(path, None)
    except Exception:
        pass
    # Platform supervisor 가 외부 기동 봇 (QA runner, 수동 실행 등) 을 감지할 수 있도록
    # PID 파일 주기적 refresh — stop.sh 가 rm 하더라도 다음 heartbeat 에 재생성.
    try:
        from src import community
        from pathlib import Path as _P
        cid = community.get_community_id()
        pid_dir = _P(__file__).resolve().parent.parent.parent / "dev"
        pid_dir.mkdir(exist_ok=True)
        for pf in (pid_dir / f".bot-{cid}.pid", pid_dir / ".bot.pid"):
            pf.write_text(str(os.getpid()))
    except Exception:
        pass


# ── Supervisor Pool tick ─────────────────────────────────
# 매 30초마다 pool.tick() — 각 supervisor의 interval은 내부에서 체크되어
# 불필요한 check() 는 skip. sync() 도 매 tick 안에서 실행되므로 scene/channel
# 변화가 늦어도 30초 내 반영.

@tasks.loop(seconds=30)
async def supervisor_tick():
    try:
        from src.bot.core import get_target_guild
        from src.supervisors.base import pool
        guild = get_target_guild()
        if not guild:
            return
        await pool.tick(guild)
    except Exception as e:
        log_writer.system(f"[supervisor-tick] 오류: {type(e).__name__}: {e}")


# ── 유나 자율 감시 + 소셜 펄스 ─────────────────────────

@tasks.loop(minutes=12)
async def yuna_watcher():
    """12분 간격 (이전 5분 → 너무 자주 보고해서 공해). 활동 감지 + 유나 판단으로 자율 대화 트리거"""
    from src.community import is_maintenance_mode
    if is_maintenance_mode():
        return

    from src.bot.core import get_target_guild
    guild = get_target_guild()
    if not guild:
        return
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

    # 채널 context — 유저가 방금 직접 참여 중인지 확인 (새 친구 "말 걸어봐" 부적절 방지).
    # dm-* 채널에 유저 발화가 최근 15분 내에 있으면 "이미 대화 중" 플래그.
    from datetime import datetime as _dt, timedelta as _td
    oc = get_user_name()
    user_id = get_user_id()
    active_user_dms: set[str] = set()
    cutoff = _dt.now() - _td(minutes=15)
    for ch in overview:
        ch_name = ch["channel"]
        if not ch_name.startswith("dm-"):
            continue
        recent = db.get_recent_messages(ch_name, limit=5)
        for r in recent:
            if r["speaker"] == user_id:
                try:
                    ts = _dt.fromisoformat(r["timestamp"])
                    if ts >= cutoff:
                        active_user_dms.add(ch_name)
                        break
                except Exception:
                    pass

    active_note = ""
    if active_user_dms:
        active_note = (
            f"\n[상황] {oc}가 지금 진행 중인 대화: {', '.join(sorted(active_user_dms))}. "
            f"이 친구들한테 '말 걸어봐' 유도 금지 — {oc} 이미 대화 중.\n"
        )

    # 유나에게 활동 알림 — 특이사항만 보고, 일상 대화는 무시
    notify = "\n".join(new_events)
    notify_prompt = (
        f"[자동알림] 최근 활동:\n{notify}\n{active_note}\n"
        f"이건 참고용이야. **대부분 무시하고 빈 응답으로 넘어가는 게 기본**.\n"
        f"보고 기준(아래 중 하나 이상 해당 시에만 {oc}한테 1~2줄 짧게 말 걸기):\n"
        f"  1) 멤버끼리 갈등·오해·상처받는 기색\n"
        f"  2) {oc} 직접 언급된 특이한 화제\n"
        f"  3) 메타 용어 누출 의심 (persona 가 AI/시스템/캐릭터 식 발언)\n"
        f"  4) 프로필 수정 필요한 새 정보 ({oc} 가 언급한 취향/상황)\n"
        f"**일상 잡담·근황 공유·게임 얘기·과제 얘기 → 응답 금지**. 그냥 빈 응답으로 끝내.\n"
        f"**이미 {oc}가 대화 중인 상대한테 '지금 가서 말 걸어봐' 같은 유도 절대 금지**.\n"
        f"\n"
        f"[보고 판단]\n"
        f"보고할 내용이 없으면 아무 글자도 쓰지 마. 네가 왜 보고 안 하는지 설명도 하지 마 — 그런 설명 자체도 보고야."
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
            stripped = resp.strip() if resp else ""
            if not stripped:
                continue
            # "(무시)", "(일상적인 대화)", "(별도 개입 없음)" 등 내부 회피 응답 필터.
            # 괄호로 시작·끝나는 단일 독백이면 유저에게 노출 금지.
            if (stripped.startswith("(") and stripped.endswith(")") and "\n" not in stripped) or \
               stripped in ("", "...", "(무시)"):
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
    from src.bot.core import get_target_guild
    guild = get_target_guild()
    if not guild:
        return
    ch = discord.utils.get(guild.text_channels, name=MGR_SYSTEM_LOG)
    if not ch:
        return

    total = _count_log_lines()
    if total <= _bot_state._last_log_line_count:
        return

    new_count = total - _bot_state._last_log_line_count
    new_lines = log_writer.tail(os.path.join(log_writer.get_log_dir(), "system.log"), new_count)

    # 에이전트 도구 호출, 프로필/관계 변동, 튜토리얼 phase, 에러 등 운영 가시성에 필요한 줄 모두 포함
    important = [l for l in new_lines if any(k in l for k in (
        "[Tool]", "[프로필]", "[관계]", "[채널]", "[감정]",
        "🔔 ACTION", "✓ ACTION", "❌", "⚠",
        "강제지시", "봇 시작", "봇 종료", "🔧",
        "튜토리얼", "Phase", "sup:tutorial",
        "Channel created", "Channel deleted",
    ))]
    if important:
        # discord 메시지 한도(2000자) 안 넘게 나눠 전송
        chunk = []
        chunk_len = 0
        for line in important:
            if chunk_len + len(line) + 8 > 1900 and chunk:
                try:
                    await ch.send("```\n" + "\n".join(chunk) + "\n```")
                except Exception:
                    pass
                chunk, chunk_len = [], 0
            chunk.append(line)
            chunk_len += len(line) + 1
        if chunk:
            try:
                await ch.send("```\n" + "\n".join(chunk) + "\n```")
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

    # 1) 유나가 오너한테 보고 (매번)
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
