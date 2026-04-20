"""
Project Glimi — Bot Core

Webhook 관리, 메시지 전송, 채널 매핑, 유틸리티 함수.
"""

import os
import re
import asyncio
from typing import Optional

import discord

from src.bot import (
    bot,
    _webhook_cache,
    CHANNEL_AGENT_MAP,
    AGENT_CHANNEL_MAP,
    GROUP_PARTICIPANTS,
    MGR_CHANNEL,
    MGR_SYSTEM_LOG,
    CREATOR_CHANNEL,
    MGR_ID,
    _system_log_queue,
    log,
)
from src.core.profile import load_profile, list_all_profiles, get_user_name, get_user_id
from src.core.runtime import runtime
from src import db, log_writer, community


# ── 프로필 이미지 ──────────────────────────────────────


def _get_profile_image_bytes(agent_id: str) -> Optional[bytes]:
    """프로필 이미지 로드 — 커뮤니티 디렉토리 우선, assets 폴백"""
    profile = load_profile(agent_id)
    fname = (profile or {}).get("profile_image_filename") or (profile or {}).get("avatar_filename")

    # DB에 파일명이 있으면 그걸로 찾기
    if fname:
        path = community.get_profile_image_path(fname)
        if path:
            with open(path, "rb") as f:
                return f.read()

    # 폴백: agent_id로 파일 스캔
    path = community.find_profile_image(agent_id)
    if path:
        with open(path, "rb") as f:
            return f.read()
    return None




# ── Webhook 관리 ────────────────────────────────────────


async def get_agent_webhook(channel: discord.TextChannel, agent_id: str) -> discord.Webhook:
    """에이전트 전용 Webhook 가져오기 (없으면 생성)"""
    cache_key = (channel.id, agent_id)
    if cache_key in _webhook_cache:
        return _webhook_cache[cache_key]
    profile = load_profile(agent_id)
    name = profile["name"] if profile else agent_id
    wh_name = f"glimi-{agent_id}"
    webhooks = await channel.webhooks()
    for wh in webhooks:
        if wh.name == wh_name:
            _webhook_cache[cache_key] = wh
            return wh
    profile_image_bytes = _get_profile_image_bytes(agent_id)
    wh = await channel.create_webhook(name=wh_name, avatar=profile_image_bytes)
    _webhook_cache[cache_key] = wh
    return wh


def _is_agent_in_channel(ch_name: str, agent_id: str, agent_name: str) -> bool:
    """에이전트가 해당 채널의 참가자인지 확인 (DB 우선, 폴백으로 채널 이름 기반)"""
    # 1. DB channels 테이블 체크
    db_participants = db.get_channel_participants(ch_name)
    if db_participants:
        return agent_id in db_participants

    # 2. DB에 없으면 채널 이름 기반 폴백
    if ch_name == MGR_CHANNEL or ch_name == MGR_SYSTEM_LOG:
        return agent_id == MGR_ID
    if ch_name == CREATOR_CHANNEL:
        return agent_id == "agent-creator-001" or agent_id == MGR_ID
    if ch_name.startswith("dm-"):
        dm_name = ch_name[3:]
        return dm_name == agent_name or agent_id == MGR_ID
    if ch_name.startswith("internal-dm-") or ch_name.startswith("internal-group-"):
        return agent_name in ch_name
    if ch_name.startswith("group-"):
        return agent_name in ch_name

    # 3. 메모리 기반 폴백
    participants = GROUP_PARTICIPANTS.get(ch_name, [])
    if participants:
        return agent_id in participants
    mapped = CHANNEL_AGENT_MAP.get(ch_name)
    if mapped:
        return mapped == agent_id

    return True  # 알 수 없는 채널은 허용


# 중복 메시지 발신 방지 — 최근 5초 내 같은 채널·에이전트·content 조합 기록.
# 과거 회귀: yuna_watcher 와 handle_dm 이 겹치면서 같은 4줄 응답이 통째로 2번 전송된 사례.
_RECENT_SENDS: dict = {}  # key=(channel_id, agent_id, content) → timestamp
_DEDUP_WINDOW_SEC = 5.0


def _dedup_and_record(channel_id: int, agent_id: str, message: str) -> bool:
    """True 반환 시 중복 (전송 skip). False 면 처음 보내는 것 (기록 + 허용)."""
    import time as _t
    now = _t.time()
    key = (channel_id, agent_id, message.strip())
    # 오래된 항목 정리 (간단 GC — 매번 돌지만 dict 작음)
    cutoff = now - _DEDUP_WINDOW_SEC * 2
    for k, ts in list(_RECENT_SENDS.items()):
        if ts < cutoff:
            _RECENT_SENDS.pop(k, None)
    prev = _RECENT_SENDS.get(key)
    if prev is not None and (now - prev) < _DEDUP_WINDOW_SEC:
        return True
    _RECENT_SENDS[key] = now
    return False


_MD_FENCE_RE = re.compile(r'^\s*(?:```|~~~)\s*\w*\s*$')


def _clean_for_chat(message: str) -> str:
    """전송 직전 정제 — 단독 마크다운 코드 펜스 (```·~~~) 제거 + 양끝 공백 trim.
    하나가 이미지 JSON 을 ``` 로 감싸다 실패한 파편이 raw 채팅으로 노출되는 케이스 방어."""
    if not message:
        return message
    lines = message.split('\n')
    cleaned = [l for l in lines if not _MD_FENCE_RE.match(l)]
    out = '\n'.join(cleaned).strip()
    return out


async def _raw_send_as_agent(channel: discord.TextChannel, agent_id: str, name: str, message: str):
    """실제 webhook 전송 + 에러 fallback. PacedSender worker가 호출.
    fallback 발생은 모두 system.log에도 남겨 (봇 이름/아바타 분리 버그 추적용)."""
    ch_name = getattr(channel, 'name', '?')
    # 마크다운 펜스 제거 (이미지 JSON 실패 부산물 등)
    message = _clean_for_chat(message)
    if not message:
        return
    # 중복 dedup — 같은 채널/에이전트/content 가 5초 내 재전송되면 skip
    if _dedup_and_record(getattr(channel, 'id', 0), agent_id, message):
        log_writer.system(f"[dedup] {name}@{ch_name}: 5초 내 동일 메시지 중복 skip")
        return
    # 디스코드 렌더링용 포맷팅 (#channel-name → <#id> 등)
    # DB/로그는 원문 유지, 여기서만 변환.
    try:
        from src.bot.formatting import format_for_discord
        from src.core.profile import get_user_name
        guild = getattr(channel, 'guild', None)
        message = format_for_discord(
            message, guild=guild,
            owner_name=get_user_name() or "",
        )
    except Exception as _fmt_err:
        log_writer.system(f"⚠ Formatting 실패 [{name}@{ch_name}]: {_fmt_err}")
    try:
        webhook = await get_agent_webhook(channel, agent_id)
        await webhook.send(content=message, username=name)
    except discord.errors.NotFound:
        _webhook_cache.pop((channel.id, agent_id), None)
        try:
            webhook = await get_agent_webhook(channel, agent_id)
            await webhook.send(content=message, username=name)
        except Exception as e2:
            log_writer.system(f"⚠ Webhook fallback [{name}@{ch_name}]: NotFound+재생성실패 ({type(e2).__name__}: {e2})")
            await channel.send(f"**{name}**: {message}")
    except discord.errors.HTTPException as e:
        if e.status == 429:
            retry_after = getattr(e, 'retry_after', 5)
            log_writer.system(f"⚠ Webhook rate limit [{name}@{ch_name}]: {retry_after}초 대기")
            await asyncio.sleep(retry_after)
            try:
                webhook = await get_agent_webhook(channel, agent_id)
                await webhook.send(content=message, username=name)
            except Exception as e3:
                log_writer.system(f"⚠ Webhook fallback [{name}@{ch_name}]: rate-limit 재시도 실패 ({type(e3).__name__}: {e3})")
                await channel.send(f"**{name}**: {message}")
        else:
            log_writer.system(f"⚠ Webhook fallback [{name}@{ch_name}]: HTTP {e.status} ({e})")
            _webhook_cache.pop((channel.id, agent_id), None)
            await channel.send(f"**{name}**: {message}")
    except Exception as e:
        log_writer.system(f"⚠ Webhook fallback [{name}@{ch_name}]: {type(e).__name__} ({e})")
        await channel.send(f"**{name}**: {message}")


async def send_as_agent(channel: discord.TextChannel, agent_id: str, message: str, paced: bool = True):
    """에이전트 메시지 전송. 기본은 PacedSender 경유 (자연스러운 페이스).

    paced=False면 즉시 전송 (시스템 에러 메시지, 복구 등에만 사용).
    채널 참가자 검증 후 enqueue.
    """
    profile = load_profile(agent_id)
    name = profile["name"] if profile else "에이전트"

    # 채널 참가자 검증
    ch_name = getattr(channel, 'name', '')
    if ch_name and not _is_agent_in_channel(ch_name, agent_id, name):
        log_writer.system(f"[필터] {name}({agent_id})의 #{ch_name} 메시지 차단 (참가자 아님): {message[:50]}")
        return

    if paced:
        from src.bot.paced_sender import paced as _paced_sender
        async def _send_fn():
            await _raw_send_as_agent(channel, agent_id, name, message)
        await _paced_sender.enqueue(channel, agent_id, message, _send_fn)
    else:
        await _raw_send_as_agent(channel, agent_id, name, message)


async def send_image_as_agent(channel: discord.TextChannel, agent_id: str, image_path: str, caption: str = ""):
    """에이전트 Webhook으로 이미지 전송"""
    import os as _os
    profile = load_profile(agent_id)
    name = profile["name"] if profile else "에이전트"

    if not _os.path.exists(image_path):
        log_writer.system(f"[이미지] 파일 없음: {image_path}")
        return

    try:
        webhook = await get_agent_webhook(channel, agent_id)
        file = discord.File(image_path, filename=_os.path.basename(image_path))
        await webhook.send(content=caption, file=file, username=name)
    except Exception as e:
        log.warning(f"이미지 전송 실패: {e}")
        try:
            file = discord.File(image_path, filename=_os.path.basename(image_path))
            await channel.send(content=f"**{name}**: {caption}", file=file)
        except Exception as e2:
            log.warning(f"이미지 fallback도 실패: {e2}")


async def update_agent_webhook_profile_image(channel: discord.TextChannel, agent_id: str) -> bool:
    """에이전트 Webhook 프로필 이미지 업데이트"""
    profile_image_bytes = _get_profile_image_bytes(agent_id)
    if not profile_image_bytes:
        return False
    try:
        webhook = await get_agent_webhook(channel, agent_id)
        await webhook.edit(avatar=profile_image_bytes)
        _webhook_cache[(channel.id, agent_id)] = webhook
        return True
    except Exception as e:
        log.warning(f"Webhook 프로필 이미지 업데이트 실패: {e}")
        return False


async def _get_plain_webhook(channel: discord.TextChannel) -> discord.Webhook:
    """아바타 없는 일반 Webhook (오너 메시지 전송용 — discord API kwarg는 avatar 유지)"""
    wh_name = "glimi-plain"
    cache_key = (channel.id, wh_name)
    if cache_key in _webhook_cache:
        return _webhook_cache[cache_key]
    webhooks = await channel.webhooks()
    for wh in webhooks:
        if wh.name == wh_name:
            _webhook_cache[cache_key] = wh
            return wh
    wh = await channel.create_webhook(name=wh_name)
    _webhook_cache[cache_key] = wh
    return wh


# ── 시스템 로그 ─────────────────────────────────────────


# 디코 #mgr-system-log 채널에 노출할 로그 키워드.
# - 에이전트가 호출하는 모든 도구 ([Tool] / [프로필] / [관계])
# - 튜토리얼/Phase 전환
# - 에러·경고
_DISCORD_LOG_KEYWORDS = {
    "❌", "⚠",
    "[Tool]", "[프로필]", "[관계]", "[채널]", "[감정]",
    "튜토리얼", "Phase", "sup:tutorial",
    "Channel created", "Channel deleted",
    "ACTION", "CMD:",  # 레거시 호환
    "개발요청", "에러", "크래시", "비정상",
}


def get_target_guild(bot_ref=None) -> Optional[discord.Guild]:
    """현재 세션의 타겟 Discord guild 반환.

    DISCORD_GUILD_ID env var 우선 — 세팅되어 있으면 그 guild 만, 못 찾으면 None
    (dev 서버 같은 엉뚱한 곳으로 쓰는 사고 방지).
    env 없으면 guilds[0] (단일 서버 운영 시 호환성용)."""
    b = bot_ref if bot_ref is not None else bot
    if not b or not b.guilds:
        return None
    target_id = os.environ.get("DISCORD_GUILD_ID")
    if target_id:
        try:
            tid = int(target_id)
        except ValueError:
            log_writer.system(f"❌ DISCORD_GUILD_ID='{target_id}' 정수 변환 실패 — guild 선택 불가")
            return None
        guild = discord.utils.get(b.guilds, id=tid)
        if not guild:
            log_writer.system(f"❌ DISCORD_GUILD_ID={tid} 서버가 봇에 없음 — 다른 서버 접근 차단")
            return None
        return guild
    return b.guilds[0]


async def send_system_log(msg: str, force: bool = False):
    """시스템 로그를 mgr-system-log 디코 채널에 전송 (크리티컬만)"""
    if not force and not any(kw in msg for kw in _DISCORD_LOG_KEYWORDS):
        return
    guild = get_target_guild()
    if not guild:
        return
    ch = discord.utils.get(guild.text_channels, name=MGR_SYSTEM_LOG)
    if ch:
        try:
            await ch.send(f"`{msg}`")
        except Exception:
            pass


def queue_system_log(msg: str, force: bool = False):
    """동기 코드에서 시스템 로그 디코 전송 예약 (크리티컬만)"""
    log_writer.system(msg)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(send_system_log(msg, force))
    except Exception:
        pass


# ── 채널 매핑 ───────────────────────────────────────────


def _build_channel_maps():
    """프로필 기반으로 채널 ↔ 에이전트 매핑 생성"""
    for p in list_all_profiles():
        agent_id = p["id"]
        name = p["name"]
        agent_type = p["type"]
        if agent_type == "persona":
            ch = f"dm-{name}"
            CHANNEL_AGENT_MAP[ch] = agent_id
            AGENT_CHANNEL_MAP[agent_id] = ch
        elif agent_type == "mgr":
            CHANNEL_AGENT_MAP[MGR_CHANNEL] = agent_id
            AGENT_CHANNEL_MAP[agent_id] = MGR_CHANNEL
        elif agent_type == "creator":
            CHANNEL_AGENT_MAP[CREATOR_CHANNEL] = agent_id
            AGENT_CHANNEL_MAP[agent_id] = CREATOR_CHANNEL


def _get_category_for_channel(ch_name: str) -> str:
    """채널 이름 → 디스코드 카테고리 이름"""
    if ch_name.startswith("mgr"):
        return "glimi-mgr"
    elif ch_name.startswith("internal-group-"):
        return "glimi-internal-group"
    elif ch_name.startswith("internal-dm-") or ch_name.startswith("internal-"):
        return "glimi-internal-dm"
    elif ch_name.startswith("group-"):
        return "glimi-group"
    elif ch_name.startswith("dm-"):
        return "glimi-dm"
    return "glimi"


async def _ensure_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    """카테고리가 없으면 생성"""
    cat = discord.utils.get(guild.categories, name=name)
    if not cat:
        cat = await guild.create_category(name)
        log.info(f"카테고리 생성: {name}")
    return cat


def _infer_channel_participants(ch_name: str, _db) -> list[str]:
    """채널 이름에서 참가자 ID 추론"""
    agents = {a["name"]: a["id"] for a in _db.list_agents()}
    if ch_name == MGR_CHANNEL or ch_name == MGR_SYSTEM_LOG:
        return [MGR_ID]
    if ch_name == CREATOR_CHANNEL:
        return ["agent-creator-001"]
    if ch_name.startswith("dm-"):
        name = ch_name[3:]
        return [agents[name]] if name in agents else []
    for prefix in ("internal-dm-", "internal-group-", "group-"):
        if ch_name.startswith(prefix):
            rest = ch_name[len(prefix):]
            return [agents[n] for n in rest.split("-") if n in agents]
    return []


async def ensure_channels(guild: discord.Guild):
    """채널 초기화. 첫 실행이면 mgr-dashboard만, 이후에는 전체 채널 보장."""
    from src import db as _db
    tutorial_done = _db.get_meta("tutorial_phase") == "complete"
    greeted = _db.get_meta("yuna_greeted")

    # DB에 대화 기록이 있으면 절대 첫 실행이 아님
    conn = _db.get_conn()
    has_messages = conn.execute("SELECT 1 FROM conversations LIMIT 1").fetchone() is not None
    conn.close()

    first_run = not greeted and not has_messages and not tutorial_done

    # 기존 glimi 채널 존재 여부 체크
    existing_glimi = []
    for cat in guild.categories:
        if cat.name.startswith("glimi"):
            existing_glimi.extend(cat.text_channels)

    if first_run:
        from src import community as _comm
        clean_flag = os.path.join(_comm.get_log_dir(), ".clean-channels")
        keep_flag = os.path.join(_comm.get_log_dir(), ".keep-channels")
        should_clean = os.path.exists(clean_flag)
        should_keep = os.path.exists(keep_flag)

        log_writer.system(
            f"[초기화] first_run=True, existing_glimi={len(existing_glimi)}개, "
            f"clean={should_clean}, keep={should_keep}"
        )

        # 기존 glimi 채널 처리 정책:
        #   .keep-channels 있음 → 유지 (레거시/운영 재시작 대비, 명시적 opt-in)
        #   그 외 (clean 플래그 있든 없든) → 전부 삭제 (default-to-clean)
        # 이전 auto-skip 분기는 제거 — DB 리셋 후 봇 재시작할 때 불필요하게
        # yuna_greeted=1 / phase=complete 자동 세팅해서 튜토리얼을 영구 스킵시키는
        # 치명적 버그였음.
        if existing_glimi and should_keep:
            log_writer.system(f"[초기화] .keep-channels 있음 → 기존 {len(existing_glimi)}개 채널 유지 + 튜토리얼 스킵")
            _db.set_meta("yuna_greeted", "1")
            _db.set_meta("tutorial_phase", "complete")
            for ch in existing_glimi:
                if not _db.get_channel_participants(ch.name):
                    parts = _infer_channel_participants(ch.name, _db)
                    if parts:
                        _db.set_channel_participants(ch.name, parts)
            first_run = False
            # keep 플래그 제거 (1회성)
            try:
                os.remove(keep_flag)
            except FileNotFoundError:
                pass
        else:
            # default: clean (명시적 clean flag 있든 없든).
            # existing_glimi 수와 무관하게 pattern 매칭되는 채널은 전부 정리 —
            # glimi-* 카테고리 밖에 orphan 된 mgr-/dm-/group-/internal- 채널까지 커버.
            # REST API로 실제 guild 상태를 가져와야 함 (gateway cache가 이전 run의 채널을
            # 누락하면 orphan이 영영 삭제 안 돼 Phase 2가 재사용하는 버그).
            glimi_patterns = ("mgr-", "dm-", "group-", "internal-")
            try:
                actual = await guild.fetch_channels()
                real_text = [c for c in actual if isinstance(c, discord.TextChannel)]
            except Exception as e:
                log_writer.system(f"⚠ fetch_channels 실패({type(e).__name__}: {e}) — cache fallback")
                real_text = list(guild.text_channels)
            deleted_any = False
            for ch in real_text:
                if any(ch.name.startswith(p) for p in glimi_patterns):
                    try:
                        await ch.delete(reason="Glimi 초기화: 채널 정리")
                        log_writer.system(f"Channel deleted: {ch.name}")
                        deleted_any = True
                    except Exception as e:
                        log_writer.system(f"⚠ Channel delete fail: {ch.name} ({type(e).__name__}: {e})")
            try:
                actual_cats = await guild.fetch_channels()
                cat_list = [c for c in actual_cats if isinstance(c, discord.CategoryChannel) and c.name.startswith("glimi")]
            except Exception:
                cat_list = [c for c in guild.categories if c.name.startswith("glimi")]
            for cat in cat_list:
                if len(cat.channels) == 0:
                    try:
                        await cat.delete()
                        log_writer.system(f"Category deleted: {cat.name}")
                    except Exception:
                        pass
            try:
                os.remove(clean_flag)
            except FileNotFoundError:
                pass
            # discord.py 내부 캐시가 gateway 이벤트로 갱신되길 잠깐 대기
            # (REST delete 직후 guild.text_channels에 삭제된 채널이 잠시 남아 있는 race 방지)
            if deleted_any:
                await asyncio.sleep(1.5)

        # mgr-dashboard만 생성 — guild.text_channels 캐시 말고 fetch로 실제 상태 확인
        try:
            actual_channels = await guild.fetch_channels()
            names = {c.name for c in actual_channels if isinstance(c, discord.TextChannel)}
        except Exception as e:
            log_writer.system(f"⚠ fetch_channels 실패({type(e).__name__}: {e}) — cache fallback")
            names = {ch.name for ch in guild.text_channels}

        if MGR_CHANNEL not in names:
            cat = await _ensure_category(guild, "glimi-mgr")
            try:
                created = await guild.create_text_channel(MGR_CHANNEL, category=cat)
                log_writer.system(f"Channel created: {MGR_CHANNEL} (id={created.id})")
            except Exception as e:
                log_writer.system(f"❌ Channel create FAIL: {MGR_CHANNEL} ({type(e).__name__}: {e})")
                raise
        else:
            log_writer.system(f"Channel (existing): {MGR_CHANNEL}")
        db.set_channel_participants(MGR_CHANNEL, [MGR_ID])
        log_writer.system("Initial setup: mgr-dashboard ready")
    else:
        # 일반 실행: 전체 채널 보장
        needed = set(CHANNEL_AGENT_MAP.keys()) | {CREATOR_CHANNEL, MGR_SYSTEM_LOG}
        existing = {ch.name: ch for ch in guild.text_channels}

        # 불필요 채널 삭제
        glimi_categories = [c for c in guild.categories if c.name.startswith("glimi")]
        for cat in glimi_categories:
            for ch in cat.text_channels:
                if ch.name not in needed:
                    try:
                        await ch.delete(reason="Glimi: 불필요 채널 정리")
                        log_writer.system(f"Channel deleted: {ch.name}")
                    except Exception:
                        pass

        existing = {ch.name: ch for ch in guild.text_channels}
        log_writer.system(f"기존 채널 {len(existing)}개, 필요 채널 {len(needed)}개")

        created = []
        for ch_name in sorted(needed):
            if ch_name not in existing:
                cat_name = _get_category_for_channel(ch_name)
                category = await _ensure_category(guild, cat_name)
                await guild.create_text_channel(ch_name, category=category)
                created.append(ch_name)
                log_writer.system(f"Channel created: {ch_name}")

            # DB에 참가자 등록 (없으면)
            if not db.get_channel_participants(ch_name):
                if ch_name == MGR_CHANNEL or ch_name == MGR_SYSTEM_LOG:
                    db.set_channel_participants(ch_name, [MGR_ID])
                elif ch_name == CREATOR_CHANNEL:
                    db.set_channel_participants(ch_name, ["agent-creator-001"])
                elif ch_name in CHANNEL_AGENT_MAP:
                    db.set_channel_participants(ch_name, [CHANNEL_AGENT_MAP[ch_name]])

        if created:
            log_writer.system(f"채널 {len(created)}개 생성 완료")
        else:
            log_writer.system("All channels exist")

    # 카테고리 순서 정렬
    from src.core.sync import CATEGORY_ORDER
    for i, cat_name in enumerate(CATEGORY_ORDER):
        cat = discord.utils.get(guild.categories, name=cat_name)
        if cat:
            try:
                await cat.edit(position=i)
            except Exception:
                pass
    log_writer.system("Categories sorted")


async def create_tutorial_channel(guild: discord.Guild, ch_name: str, participants: list[str] = None) -> discord.TextChannel:
    """튜토리얼 중 단계별 채널 생성 + 참가자 등록.
    성공/실패/existing 세 경로 모두 system.log에 남겨 추적 가능하게.
    discord.py gateway 캐시 지연 방지로 fetch_channels로 실제 guild 상태 조회."""
    # 캐시 대신 REST API로 실제 상태 확인
    try:
        actual = await guild.fetch_channels()
        existing = next(
            (c for c in actual if isinstance(c, discord.TextChannel) and c.name == ch_name),
            None,
        )
    except Exception:
        existing = discord.utils.get(guild.text_channels, name=ch_name)

    if existing:
        if participants:
            db.set_channel_participants(ch_name, participants)
        log_writer.system(f"튜토리얼 Channel (existing): {ch_name} (id={existing.id})")
        return existing
    cat_name = _get_category_for_channel(ch_name)
    try:
        category = await _ensure_category(guild, cat_name)
    except Exception as e:
        log_writer.system(f"❌ 튜토리얼 Category fail: {cat_name} ({type(e).__name__}: {e})")
        raise
    try:
        ch = await guild.create_text_channel(ch_name, category=category)
    except Exception as e:
        log_writer.system(f"❌ 튜토리얼 Channel create fail: {ch_name} ({type(e).__name__}: {e})")
        raise
    if participants:
        db.set_channel_participants(ch_name, participants)
    log_writer.system(f"튜토리얼 Channel created: {ch_name} (id={ch.id}, category={cat_name})")
    return ch


async def sync_profile_images(guild: discord.Guild):
    """glimi 카테고리들 내 모든 Webhook 프로필 이미지를 로컬 이미지와 동기화"""
    glimi_categories = [c for c in guild.categories if c.name.startswith("glimi")]
    if not glimi_categories:
        log_writer.system("Profile image sync: no glimi categories — skip")
        return
    updated = 0
    total_channels = sum(len(cat.text_channels) for cat in glimi_categories)
    scanned = 0
    for cat in glimi_categories:
        for channel in cat.text_channels:
            scanned += 1
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if not wh.name.startswith("glimi-"):
                    continue
                agent_id = wh.name.replace("glimi-", "", 1)
                profile_image_bytes = _get_profile_image_bytes(agent_id)
                if not profile_image_bytes:
                    continue
                try:
                    await wh.edit(avatar=profile_image_bytes)
                    updated += 1
                    log_writer.system(f"  Webhook 프로필 이미지 업데이트: {agent_id} → #{channel.name}")
                except Exception:
                    pass
            log_writer.system(f"Webhook 스캔: #{channel.name} ({scanned}/{total_channels})")
    log_writer.system(f"Profile image sync done: {updated}개 Webhook updated")




# ── 유틸리티 ────────────────────────────────────────────


def _split_for_chat(text: str) -> list[str]:
    """하나의 응답을 카톡 스타일 짧은 메시지들로 분할 + 중복 제거"""
    text = text.strip()
    if not text:
        return ["..."]
    if len(text) <= 40:
        return [text]
    parts = re.split(r'(?<=[.?!~ㅋㅠㅎ])\s+|\n+', text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        return [text]
    merged = []
    for p in parts:
        if merged and len(merged[-1]) < 5:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)

    def _normalize(s):
        return re.sub(r'[.?!,~\s…·ㅋㅎㅠ]', '', s).lower()

    unique = []
    seen_keys = set()
    for m in merged:
        key = _normalize(m)
        if not key:
            unique.append(m)
            continue
        if key in seen_keys:
            continue
        is_subset = False
        for existing in unique:
            if key in _normalize(existing):
                is_subset = True
                break
        if not is_subset:
            seen_keys.add(key)
            unique.append(m)
    merged = unique
    if len(merged) > 4:
        result = merged[:3]
        result.append(" ".join(merged[3:]))
        return result
    return merged if merged else [text]


def _resolve_group_members(channel_name: str) -> list[dict]:
    """채널명에서 참여 에이전트 추론 (group-이름1-이름2 → 에이전트 목록)"""
    all_agents = db.list_agents()
    agent_by_name = {a["name"]: a for a in all_agents}
    rest = channel_name.removeprefix("group-")
    matched = []
    remaining = rest
    sorted_names = sorted(agent_by_name.keys(), key=len, reverse=True)
    for name in sorted_names:
        if name in remaining:
            matched.append(agent_by_name[name])
            remaining = remaining.replace(name, "", 1)
    if matched:
        GROUP_PARTICIPANTS[channel_name] = [a["id"] for a in matched]
        log.info(f"[Group] {channel_name} 참여자 추론: {[a['name'] for a in matched]}")
    return matched
