"""
Project Chaos — Bot Core

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
    wh_name = f"chaos-{agent_id}"
    webhooks = await channel.webhooks()
    for wh in webhooks:
        if wh.name == wh_name:
            _webhook_cache[cache_key] = wh
            return wh
    avatar_bytes = _get_avatar_bytes(agent_id)
    wh = await channel.create_webhook(name=wh_name, avatar=avatar_bytes)
    _webhook_cache[cache_key] = wh
    return wh


async def send_as_agent(channel: discord.TextChannel, agent_id: str, message: str):
    """에이전트 전용 Webhook으로 메시지 전송"""
    profile = load_profile(agent_id)
    name = profile["name"] if profile else "에이전트"
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
    log_writer.agent_discord(agent_id, channel.name, message)
    log_writer.chat(channel.name, name, message)


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
    wh_name = "chaos-plain"
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
        return "chaos-mgr"
    elif ch_name.startswith("internal-group-"):
        return "chaos-internal-group"
    elif ch_name.startswith("internal-dm-") or ch_name.startswith("internal-"):
        return "chaos-internal-dm"
    elif ch_name.startswith("group-"):
        return "chaos-group"
    elif ch_name.startswith("dm-"):
        return "chaos-dm"
    return "chaos"


async def _ensure_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
    """카테고리가 없으면 생성"""
    cat = discord.utils.get(guild.categories, name=name)
    if not cat:
        cat = await guild.create_category(name)
        log.info(f"카테고리 생성: {name}")
    return cat


async def ensure_channels(guild: discord.Guild):
    """필요한 채널이 없으면 자동 생성 (카테고리별 정리)"""
    existing = {ch.name: ch for ch in guild.text_channels}
    needed_channels = list(CHANNEL_AGENT_MAP.keys()) + [CREATOR_CHANNEL, MGR_SYSTEM_LOG]

    # 기존 chaos 단일 카테고리 호환: 이미 있으면 유지
    created = []
    for ch_name in needed_channels:
        if ch_name not in existing:
            cat_name = _get_category_for_channel(ch_name)
            category = await _ensure_category(guild, cat_name)
            await guild.create_text_channel(ch_name, category=category)
            created.append(ch_name)
    if created:
        log.info(f"채널 생성: {', '.join(created)}")
    else:
        log.info("모든 채널 이미 존재")


async def sync_avatars(guild: discord.Guild):
    """chaos 카테고리들 내 모든 Webhook 아바타를 로컬 이미지와 동기화"""
    chaos_categories = [c for c in guild.categories if c.name.startswith("chaos")]
    if not chaos_categories:
        return
    updated = 0
    for cat in chaos_categories:
        for channel in cat.text_channels:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if not wh.name.startswith("chaos-"):
                    continue
                agent_id = wh.name.replace("chaos-", "", 1)
                avatar_bytes = _get_avatar_bytes(agent_id)
                if not avatar_bytes:
                    continue
                try:
                    await wh.edit(avatar=avatar_bytes)
                    updated += 1
                except Exception:
                    pass
    if updated:
        log.info(f"아바타 동기화: {updated}개 Webhook 업데이트")


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
