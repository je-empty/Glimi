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


# ── 아바타 ──────────────────────────────────────────────


def _get_avatar_bytes(agent_id: str) -> Optional[bytes]:
    """아바타 이미지 로드 — 커뮤니티 디렉토리 우선, assets 폴백"""
    profile = load_profile(agent_id)
    fname = (profile or {}).get("avatar_filename")

    # DB에 파일명이 있으면 그걸로 찾기
    if fname:
        path = community.get_avatar_path(fname)
        if path:
            with open(path, "rb") as f:
                return f.read()

    # 폴백: agent_id로 파일 스캔
    path = community.find_avatar(agent_id)
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
    avatar_bytes = _get_avatar_bytes(agent_id)
    wh = await channel.create_webhook(name=wh_name, avatar=avatar_bytes)
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


async def _raw_send_as_agent(channel: discord.TextChannel, agent_id: str, name: str, message: str):
    """실제 webhook 전송 + 에러 fallback. PacedSender worker가 호출."""
    try:
        webhook = await get_agent_webhook(channel, agent_id)
        await webhook.send(content=message, username=name)
    except discord.errors.NotFound:
        _webhook_cache.pop((channel.id, agent_id), None)
        try:
            webhook = await get_agent_webhook(channel, agent_id)
            await webhook.send(content=message, username=name)
        except Exception as e2:
            log.warning(f"Webhook 재생성도 실패, fallback: {e2}")
            await channel.send(f"**{name}**: {message}")
    except discord.errors.HTTPException as e:
        if e.status == 429:
            retry_after = getattr(e, 'retry_after', 5)
            log.warning(f"Webhook rate limit, {retry_after}초 대기")
            await asyncio.sleep(retry_after)
            try:
                webhook = await get_agent_webhook(channel, agent_id)
                await webhook.send(content=message, username=name)
            except Exception:
                await channel.send(f"**{name}**: {message}")
        else:
            log.warning(f"Webhook HTTP 오류 ({e.status}), fallback: {e}")
            _webhook_cache.pop((channel.id, agent_id), None)
            await channel.send(f"**{name}**: {message}")
    except Exception as e:
        log.warning(f"Webhook 실패, fallback: {e}")
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


async def update_agent_webhook_avatar(channel: discord.TextChannel, agent_id: str) -> bool:
    """에이전트 Webhook 아바타 업데이트"""
    avatar_bytes = _get_avatar_bytes(agent_id)
    if not avatar_bytes:
        return False
    try:
        webhook = await get_agent_webhook(channel, agent_id)
        await webhook.edit(avatar=avatar_bytes)
        _webhook_cache[(channel.id, agent_id)] = webhook
        return True
    except Exception as e:
        log.warning(f"Webhook 아바타 업데이트 실패: {e}")
        return False


async def _get_plain_webhook(channel: discord.TextChannel) -> discord.Webhook:
    """아바타 없는 일반 Webhook (오너 메시지 전송용)"""
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


# 디코 시스템 로그에 보낼 키워드 (크리티컬만)
_DISCORD_LOG_KEYWORDS = {"❌", "ACTION", "CMD:", "개발요청", "에러", "크래시", "비정상"}


async def send_system_log(msg: str, force: bool = False):
    """시스템 로그를 mgr-system-log 디코 채널에 전송 (크리티컬만)"""
    if not force and not any(kw in msg for kw in _DISCORD_LOG_KEYWORDS):
        return
    if not bot.guilds:
        return
    guild = bot.guilds[0]
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
    onboarding_done = _db.get_meta("onboarding_phase") == "complete"
    greeted = _db.get_meta("yuna_greeted")

    # DB에 대화 기록이 있으면 절대 첫 실행이 아님
    conn = _db.get_conn()
    has_messages = conn.execute("SELECT 1 FROM conversations LIMIT 1").fetchone() is not None
    conn.close()

    first_run = not greeted and not has_messages and not onboarding_done

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

        if existing_glimi and not should_clean and not should_keep:
            # DB 비어있는데 디코 채널이 있음 → 이전 서버 흔적
            log_writer.system(f"[초기화] 기존 glimi 채널 {len(existing_glimi)}개 발견 — 유지하고 온보딩 스킵")
            # 기존 채널 유지 + 온보딩 완료로 보정
            _db.set_meta("yuna_greeted", "1")
            _db.set_meta("onboarding_phase", "complete")
            # 채널 참가자 등록 (DB에 없으면)
            for ch in existing_glimi:
                if not _db.get_channel_participants(ch.name):
                    parts = _infer_channel_participants(ch.name, _db)
                    if parts:
                        _db.set_channel_participants(ch.name, parts)
            first_run = False  # 일반 실행으로 전환
        elif should_clean:
            # 명시적 정리 요청 — 이름 패턴 기반 (카테고리 불문, orphan 포함)
            glimi_patterns = ("mgr-", "dm-", "group-", "internal-")
            for ch in list(guild.text_channels):
                if any(ch.name.startswith(p) for p in glimi_patterns):
                    try:
                        await ch.delete(reason="Glimi 초기화: 채널 정리")
                        log_writer.system(f"Channel deleted: {ch.name}")
                    except Exception:
                        pass
            # 빈 glimi-* 카테고리 제거
            for cat in [c for c in guild.categories if c.name.startswith("glimi")]:
                if len(cat.channels) == 0:
                    try:
                        await cat.delete()
                        log_writer.system(f"Category deleted: {cat.name}")
                    except Exception:
                        pass
            # 플래그 제거
            try:
                os.remove(clean_flag)
            except FileNotFoundError:
                pass

        # mgr-dashboard만 생성
        existing = {ch.name: ch for ch in guild.text_channels}
        if MGR_CHANNEL not in existing:
            cat = await _ensure_category(guild, "glimi-mgr")
            await guild.create_text_channel(MGR_CHANNEL, category=cat)
            log_writer.system(f"Channel created: {MGR_CHANNEL}")
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


async def create_onboarding_channel(guild: discord.Guild, ch_name: str, participants: list[str] = None) -> discord.TextChannel:
    """온보딩 중 단계별 채널 생성 + 참가자 등록"""
    existing = discord.utils.get(guild.text_channels, name=ch_name)
    if existing:
        if participants:
            db.set_channel_participants(ch_name, participants)
        return existing
    cat_name = _get_category_for_channel(ch_name)
    category = await _ensure_category(guild, cat_name)
    ch = await guild.create_text_channel(ch_name, category=category)
    if participants:
        db.set_channel_participants(ch_name, participants)
    log_writer.system(f"온보딩 Channel created: {ch_name}")
    return ch


async def sync_avatars(guild: discord.Guild):
    """glimi 카테고리들 내 모든 Webhook 아바타를 로컬 이미지와 동기화"""
    glimi_categories = [c for c in guild.categories if c.name.startswith("glimi")]
    if not glimi_categories:
        log_writer.system("Avatar sync: no glimi categories — skip")
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
                avatar_bytes = _get_avatar_bytes(agent_id)
                if not avatar_bytes:
                    continue
                try:
                    await wh.edit(avatar=avatar_bytes)
                    updated += 1
                    log_writer.system(f"  Webhook 아바타 업데이트: {agent_id} → #{channel.name}")
                except Exception:
                    pass
            log_writer.system(f"Webhook 스캔: #{channel.name} ({scanned}/{total_channels})")
    log_writer.system(f"Avatar sync done: {updated}개 Webhook updated")


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
