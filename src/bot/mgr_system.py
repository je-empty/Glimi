"""
Project Glimi — Yuna Autonomous System

유나(agent-mgr-001)의 자율 행동 시스템.
CMD/QUERY 태그 파싱, 실행, 개발 요청, ACTION 승인 등.
"""
import os
import json
import asyncio
import random
from datetime import datetime
from src.core.timeutil import now_utc_iso

import discord

import src.bot as _bot_state
from src import db
from src import log_writer
from src import community
from src.core.profile import (
    load_profile, list_all_profiles, get_user_name, get_user_id,
)
from src.core.runtime import runtime
from src.core.conversation import (
    start_conversation, stop_conversation, list_active_conversations,
    detect_room_request,
)
from src.bot import (
    bot, log, MGR_CHANNEL, MGR_SYSTEM_LOG, CREATOR_CHANNEL, MGR_ID,
    CHANNEL_AGENT_MAP, AGENT_CHANNEL_MAP, GROUP_PARTICIPANTS,
    _webhook_cache, DEV_DIR, DEV_PENDING, DEV_RESULT,
    DAILY_SOCIAL_LIMIT,
)
from src.bot.core import (
    send_as_agent, send_system_log, get_agent_webhook,
    _split_for_chat, _get_plain_webhook,
)


# ── CMD/QUERY 파싱 + 실행 ──────────────────────────────


def _sanitize_dm_name(agent_name: str) -> str:
    """페르소나 이름 → Discord 친화적 dm 채널 이름.

    회귀: name 에 공백 (예: '유키 아스나') 있으면 Discord 가 자동으로 dash 변환 → DB/runtime
    캐시는 공백 그대로 → 채널 lookup 미스매치 → 첫 인사 트리거 실패 + 채널 미인식.
    공백 + 일부 특수문자를 dash 로 정규화. 한글·영문·숫자는 보존.
    """
    import re
    if not agent_name:
        return "dm-unknown"
    # whitespace → dash, 그 외 부적합 문자 제거 (한글·영문·숫자·dash·underscore 만 보존)
    s = re.sub(r"\s+", "-", agent_name.strip())
    s = re.sub(r"[^\w\-가-힣ㄱ-ㅎㅏ-ㅣ]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return f"dm-{s}" if s else "dm-unknown"


async def parse_and_execute_actions(
    report_channel: discord.TextChannel,
    responses: list[str],
    guild: discord.Guild,
    caller_agent_id: str = None,
) -> list[str]:
    """
    신규 Tool Protocol 기반 실행.

    - runtime에 stash된 tool_calls를 dispatcher로 실행
    - query 결과 있으면 followup generate → 분석 응답 추가 반환
    - 응답 텍스트(responses)는 chat만 (tool 블록은 이미 runtime이 제거)

    caller_agent_id: 호출한 에이전트. None이면 MGR_ID (유나) 가정.
    """
    from src.core.tools import run_tools, ToolContext, format_results_block, get_tool
    from src.core.runtime import runtime

    cleaned = [r.strip() for r in responses if r and r.strip()]
    agent_id = caller_agent_id or MGR_ID
    profile = load_profile(agent_id) or {}
    agent_type = profile.get("type", "mgr")

    calls = runtime.pop_tool_calls(agent_id)
    if not calls:
        return cleaned

    ctx = ToolContext(
        caller_agent_id=agent_id,
        caller_agent_type=agent_type,
        channel_name=getattr(report_channel, "name", "") or "",
        channel_obj=report_channel,
        guild=guild,
    )
    results = await run_tools(calls, ctx)

    for r in results:
        mark = "✓" if r.ok else "✗"
        tail = str(r.data)[:80] if r.ok and r.data else (r.error or "")
        log_writer.system(f"[Tool] {mark} {r.tool} {tail}")

    # 쿼리 결과 있으면 다음 턴에 <tool_results> 주입 + followup 생성
    has_query_result = any(
        (get_tool(r.tool) and get_tool(r.tool).category == "query") for r in results if r.ok
    )
    if has_query_result:
        block = format_results_block(results)
        runtime.stash_tool_results(agent_id, ctx.channel_name, block)
        followup = await _tool_followup_generate(report_channel, agent_id, guild)
        if followup:
            cleaned.extend(followup)

    return cleaned


async def _tool_followup_generate(
    report_channel: discord.TextChannel,
    agent_id: str,
    guild: discord.Guild,
) -> list[str]:
    """tool_results가 stash된 상태에서 에이전트 재생성 — 결과 분석 chat만 반환.

    runtime._build_prompt가 stash된 결과를 user_message 앞에 삽입.
    """
    loop = asyncio.get_event_loop()
    ch_name = getattr(report_channel, "name", "") or ""
    trigger = "(위 tool_results를 보고 자연스럽게 마무리해. 결과를 대화에 녹여서 간결하게. 추가 도구 호출 불필요하면 tools 블록 비워도 돼.)"
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response(
            agent_id, ch_name, trigger, log_user_message=False
        )
    )
    return [r for r in responses if r and r.strip()]


async def execute_yuna_query(query_str: str, guild: discord.Guild = None) -> str:
    """유나의 QUERY 실행 → 텍스트 결과 반환 (DB + 디스코드 직접 조회)"""
    query_str = query_str.strip()

    # JSON 형식 지원
    if query_str.startswith("{"):
        try:
            import json as _json
            data = _json.loads(query_str)
            cmd = data.get("type", data.get("cmd", ""))
            args = data.get("name", data.get("target", data.get("args", "")))
            if isinstance(args, str):
                args = _resolve_agent_name(args) if args else ""
        except (ValueError, KeyError):
            parts = query_str.split(None, 1)
            cmd = parts[0]
            args = parts[1] if len(parts) > 1 else ""
    else:
        parts = query_str.split(None, 1)
        cmd = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        # 이름 인자 해석 (프로필, 관계, 발화, 이벤트 등)
        if cmd in ("프로필", "관계", "발화", "이벤트") and args:
            args = _resolve_agent_name(args.split()[0]) + (" " + " ".join(args.split()[1:]) if len(args.split()) > 1 else "")

    log.info(f"[유나QUERY] {cmd} {args}")

    if cmd == "채널목록":
        overview = db.get_channel_overview()
        if not overview:
            return "[조회결과] 대화 기록 없음"
        lines = ["[채널 활동 현황]"]
        for ch in overview:
            last = ch["last_active"][:16] if ch["last_active"] else "?"
            lines.append(f"- {ch['channel']}: {ch['msg_count']}건, 참여자 {ch['speakers']}명, 마지막 {last}")
        return "\n".join(lines)

    elif cmd == "로그":
        log_parts = args.split()
        ch_name = log_parts[0] if log_parts else ""
        limit = int(log_parts[1]) if len(log_parts) > 1 and log_parts[1].isdigit() else 30
        limit = min(limit, 100)  # 최대 100건

        if not ch_name:
            return "[조회결과] 채널명 필요"

        messages = db.get_recent_messages(ch_name, limit=limit)
        if not messages:
            return f"[조회결과] {ch_name}에 대화 없음"

        lines = [f"[{ch_name} 최근 {len(messages)}건]"]
        for m in messages:
            ts = m["timestamp"][11:16] if m["timestamp"] else ""
            speaker = m["speaker"]
            if speaker == get_user_id():
                speaker = get_user_name()
            else:
                agent = db.get_agent(speaker)
                if agent:
                    speaker = agent["name"]
            lines.append(f"{ts} {speaker}: {m['message']}")
        return "\n".join(lines)

    elif cmd == "검색":
        keyword = args.strip()
        if not keyword:
            return "[조회결과] 검색어 필요"

        results = db.search_messages(keyword, limit=20)
        if not results:
            return f"[조회결과] '{keyword}' 검색 결과 없음"

        lines = [f"['{keyword}' 검색 결과 {len(results)}건]"]
        for m in results:
            ts = m["timestamp"][11:16] if m["timestamp"] else ""
            speaker = m["speaker"]
            if speaker == get_user_id():
                speaker = get_user_name()
            else:
                agent = db.get_agent(speaker)
                if agent:
                    speaker = agent["name"]
            ch = m["channel"]
            lines.append(f"{ts} [{ch}] {speaker}: {m['message']}")
        return "\n".join(lines)

    elif cmd == "발화":
        # 특정 에이전트의 전체 발화 조회
        agent_name = args.strip()
        agents = db.list_agents()
        target = next((a for a in agents if a["name"] == agent_name), None)
        if not target:
            return f"[조회결과] {agent_name} 찾을 수 없음"

        messages = db.get_agent_messages(target["id"], limit=30)
        if not messages:
            return f"[조회결과] {agent_name} 발화 없음"

        lines = [f"[{agent_name} 최근 발화 {len(messages)}건]"]
        for m in messages:
            ts = m["timestamp"][11:16] if m["timestamp"] else ""
            emotion = f"({m['context_emotion']})" if m.get("context_emotion") else ""
            lines.append(f"{ts} [{m['channel']}] {m['message']} {emotion}")
        return "\n".join(lines)

    elif cmd == "멤버목록":
        agents = db.list_agents()
        lines = ["[멤버 목록]"]
        for a in agents:
            profile = load_profile(a["id"])
            rel = (profile or {}).get("relationship_to_owner", {}).get("type", "")
            lines.append(f"- {a['name']} ({a.get('type','?')}) | {a.get('age', (profile or {}).get('age', '?'))}살 | {rel} | {a['status']}")
        return "\n".join(lines)

    elif cmd == "프로필":
        agent_name = args.strip()
        agents = db.list_agents()
        target = next((a for a in agents if a["name"] == agent_name), None)
        if not target:
            return f"[조회결과] {agent_name} 찾을 수 없음"
        profile = load_profile(target["id"])
        if not profile:
            return f"[조회결과] {agent_name} 프로필 없음"
        import json as json_mod
        return f"[{agent_name} 프로필]\n{json_mod.dumps(profile, ensure_ascii=False, indent=2)}"

    elif cmd == "관계":
        agent_name = args.strip()
        if not agent_name:
            # 전체 관계
            conn = db.get_conn()
            rows = conn.execute("SELECT * FROM relationships ORDER BY intimacy_score DESC").fetchall()
            conn.close()
            lines = ["[전체 관계 현황]"]
            for r in rows:
                a_name = get_user_name() if r["agent_a"] == get_user_id() else (db.get_agent(r["agent_a"]) or {}).get("name", r["agent_a"])
                b_name = (db.get_agent(r["agent_b"]) or {}).get("name", r["agent_b"])
                lines.append(f"- {a_name}↔{b_name}: {r['type']}({r['intimacy_score']}) {r['dynamics'] or ''}")
            return "\n".join(lines)
        else:
            # 특정 에이전트의 관계
            agents = db.list_agents()
            target = next((a for a in agents if a["name"] == agent_name), None)
            agent_id = target["id"] if target else (get_user_id() if agent_name == get_user_name() else None)
            if not agent_id:
                return f"[조회결과] {agent_name} 찾을 수 없음"
            rels = db.get_all_relationships(agent_id)
            lines = [f"[{agent_name} 관계]"]
            for r in rels:
                other_id = r["agent_b"] if r["agent_a"] == agent_id else r["agent_a"]
                other_name = get_user_name() if other_id == get_user_id() else (db.get_agent(other_id) or {}).get("name", other_id)
                lines.append(f"- {other_name}: {r['type']}({r['intimacy_score']}) {r['dynamics'] or ''}")
            return "\n".join(lines)

    elif cmd == "이벤트":
        agent_name = args.strip() if args.strip() else None
        if agent_name:
            agents = db.list_agents()
            target = next((a for a in agents if a["name"] == agent_name), None)
            events = db.get_events(participant=target["id"] if target else agent_name, limit=15)
        else:
            events = db.get_events(limit=15)
        if not events:
            return "[조회결과] 이벤트 없음"
        lines = ["[이벤트 이력]"]
        for e in events:
            ts = e["timestamp"][:16] if e["timestamp"] else ""
            lines.append(f"- {ts} [{e['event_type']}] {e['description']} (영향: {e.get('impact', '')})")
        return "\n".join(lines)

    # ── 디스코드 직접 조회 (discord.py API) ──

    elif cmd == "디코로그":
        if not guild:
            return "[조회결과] 디스코드 연결 없음"
        log_parts = args.split()
        ch_name = log_parts[0] if log_parts else ""
        limit = int(log_parts[1]) if len(log_parts) > 1 and log_parts[1].isdigit() else 30
        limit = min(limit, 200)
        if not ch_name:
            return "[조회결과] 채널명 필요"
        channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not channel:
            return f"[조회결과] 디스코드에 #{ch_name} 채널 없음"
        messages = []
        async for msg in channel.history(limit=limit):
            ts = msg.created_at.strftime("%m/%d %H:%M")
            author = msg.author.display_name
            content = msg.content or "(첨부/임베드)"
            messages.append(f"{ts} {author}: {content}")
        messages.reverse()
        if not messages:
            return f"[조회결과] #{ch_name} 디스코드 메시지 없음"
        return f"[디스코드 #{ch_name} 실제 메시지 {len(messages)}건]\n" + "\n".join(messages)

    elif cmd == "디코채널목록":
        if not guild:
            return "[조회결과] 디스코드 연결 없음"
        lines = ["[디스코드 서버 채널 목록]"]
        categories = guild.categories
        # 카테고리 없는 채널
        no_cat = [ch for ch in guild.text_channels if ch.category is None]
        if no_cat:
            lines.append("── (카테고리 없음) ──")
            for ch in sorted(no_cat, key=lambda c: c.position):
                topic = f" | 토픽: {ch.topic}" if ch.topic else ""
                lines.append(f"  #{ch.name}{topic}")
        for cat in sorted(categories, key=lambda c: c.position):
            lines.append(f"── {cat.name} ──")
            for ch in sorted(cat.text_channels, key=lambda c: c.position):
                topic = f" | 토픽: {ch.topic}" if ch.topic else ""
                lines.append(f"  #{ch.name}{topic}")
        # 음성 채널
        voice_channels = guild.voice_channels
        if voice_channels:
            lines.append("── 음성 채널 ──")
            for vc in sorted(voice_channels, key=lambda c: c.position):
                members = ", ".join(m.display_name for m in vc.members) if vc.members else "비어있음"
                lines.append(f"  🔊 {vc.name} ({members})")
        return "\n".join(lines)

    elif cmd == "디코멤버":
        if not guild:
            return "[조회결과] 디스코드 연결 없음"
        member_name = args.strip()
        if not member_name:
            # 전체 멤버 목록
            lines = [f"[디스코드 서버 멤버 {guild.member_count}명]"]
            for m in sorted(guild.members, key=lambda m: m.display_name):
                status = str(m.status) if hasattr(m, 'status') else "?"
                roles = ", ".join(r.name for r in m.roles if r.name != "@everyone")
                bot_tag = " [BOT]" if m.bot else ""
                lines.append(f"  {m.display_name} (@{m.name}){bot_tag} | 역할: {roles or '없음'} | 상태: {status}")
            return "\n".join(lines)
        else:
            # 특정 멤버 검색
            member = discord.utils.find(
                lambda m: member_name in m.display_name or member_name in m.name,
                guild.members
            )
            if not member:
                return f"[조회결과] '{member_name}' 멤버 찾을 수 없음"
            roles = ", ".join(r.name for r in member.roles if r.name != "@everyone")
            joined = member.joined_at.strftime("%Y-%m-%d %H:%M") if member.joined_at else "?"
            created = member.created_at.strftime("%Y-%m-%d %H:%M") if member.created_at else "?"
            status = str(member.status) if hasattr(member, 'status') else "?"
            bot_tag = " [BOT]" if member.bot else ""
            lines = [
                f"[멤버 정보: {member.display_name}]{bot_tag}",
                f"  오너명: @{member.name} (ID: {member.id})",
                f"  닉네임: {member.nick or '없음'}",
                f"  역할: {roles or '없음'}",
                f"  서버 가입: {joined}",
                f"  계정 생성: {created}",
                f"  상태: {status}",
            ]
            if member.activity:
                lines.append(f"  활동: {member.activity}")
            return "\n".join(lines)

    elif cmd == "디코채널정보":
        if not guild:
            return "[조회결과] 디스코드 연결 없음"
        ch_name = args.strip()
        if not ch_name:
            return "[조회결과] 채널명 필요"
        channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not channel:
            # 음성채널도 검색
            channel = discord.utils.get(guild.voice_channels, name=ch_name)
        if not channel:
            return f"[조회결과] #{ch_name} 채널 없음"
        created = channel.created_at.strftime("%Y-%m-%d %H:%M") if channel.created_at else "?"
        lines = [
            f"[채널 정보: #{channel.name}]",
            f"  ID: {channel.id}",
            f"  타입: {str(channel.type)}",
            f"  카테고리: {channel.category.name if channel.category else '없음'}",
            f"  생성일: {created}",
            f"  위치: {channel.position}",
        ]
        if hasattr(channel, 'topic'):
            lines.append(f"  토픽: {channel.topic or '없음'}")
        if hasattr(channel, 'slowmode_delay'):
            lines.append(f"  슬로우모드: {channel.slowmode_delay}초")
        if hasattr(channel, 'nsfw'):
            lines.append(f"  NSFW: {channel.nsfw}")
        # 권한 오버라이드
        if channel.overwrites:
            lines.append("  권한 오버라이드:")
            for target, overwrite in channel.overwrites.items():
                allow, deny = overwrite.pair()
                target_name = target.name if hasattr(target, 'name') else str(target)
                if allow.value or deny.value:
                    lines.append(f"    {target_name}: 허용={allow.value}, 거부={deny.value}")
        return "\n".join(lines)

    elif cmd == "디코서버":
        if not guild:
            return "[조회결과] 디스코드 연결 없음"
        created = guild.created_at.strftime("%Y-%m-%d %H:%M") if guild.created_at else "?"
        lines = [
            f"[서버 정보: {guild.name}]",
            f"  ID: {guild.id}",
            f"  소유자: {guild.owner.display_name if guild.owner else '?'}",
            f"  멤버 수: {guild.member_count}",
            f"  텍스트 채널: {len(guild.text_channels)}개",
            f"  음성 채널: {len(guild.voice_channels)}개",
            f"  카테고리: {len(guild.categories)}개",
            f"  역할: {len(guild.roles)}개",
            f"  이모지: {len(guild.emojis)}개",
            f"  부스트 레벨: {guild.premium_tier}",
            f"  생성일: {created}",
        ]
        lines.append(f"  역할 목록: {', '.join(r.name for r in guild.roles if r.name != '@everyone')}")
        return "\n".join(lines)

    elif cmd == "디코핀":
        if not guild:
            return "[조회결과] 디스코드 연결 없음"
        ch_name = args.strip()
        if not ch_name:
            return "[조회결과] 채널명 필요"
        channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not channel:
            return f"[조회결과] #{ch_name} 채널 없음"
        pins = await channel.pins()
        if not pins:
            return f"[조회결과] #{ch_name} 고정 메시지 없음"
        lines = [f"[#{ch_name} 고정 메시지 {len(pins)}건]"]
        for pin in pins:
            ts = pin.created_at.strftime("%m/%d %H:%M")
            lines.append(f"  {ts} {pin.author.display_name}: {pin.content or '(첨부/임베드)'}")
        return "\n".join(lines)

    else:
        return f"[조회결과] 알 수 없는 쿼리: {cmd}"


def _resolve_agent_name(name_or_alias: str) -> str:
    """이름, 별칭, ID → 실제 에이전트 이름으로 변환"""
    if not name_or_alias:
        return name_or_alias
    name_or_alias = name_or_alias.strip()

    # 정확한 이름 매치
    for a in db.list_agents():
        if a["name"] == name_or_alias:
            return a["name"]

    # ID 매치
    agent = db.get_agent(name_or_alias)
    if agent:
        return agent["name"]

    # 별칭 매치 (pet_name)
    conn = db.get_conn()
    rels = conn.execute("SELECT * FROM relationships").fetchall()
    conn.close()
    for r in rels:
        r = dict(r)
        if r.get("pet_name_a_to_b") == name_or_alias:
            target = db.get_agent(r["agent_b"])
            if target:
                return target["name"]
        if r.get("pet_name_b_to_a") == name_or_alias:
            target = db.get_agent(r["agent_a"])
            if target:
                return target["name"]

    # 부분 매치 (앞 글자)
    for a in db.list_agents():
        if a["name"].startswith(name_or_alias):
            return a["name"]

    return name_or_alias  # 해석 불가 → 원본 반환


# ── 톡방/대화 관리 ───────────────────────────────────────


async def yuna_create_room(report_channel, args_str, guild):
    """유나가 톡방 생성 — 에이전트끼리면 internal, 오너 포함이면 group"""
    agents_db = db.list_agents()
    agent_names = {a["name"]: a for a in agents_db}

    tokens = args_str.split()
    participants = []
    topic_parts = []
    has_owner = False
    for t in tokens:
        if t == get_user_name():
            has_owner = True
        elif t in agent_names:
            participants.append(agent_names[t])
        else:
            # 부분 매칭 (유나→서유나, 하나→윤하나, 서연→최서연 등)
            matched = next((a for name, a in agent_names.items() if t in name), None)
            if matched:
                participants.append(matched)
            else:
                topic_parts.append(t)

    min_needed = 1 if has_owner else 2
    if len(participants) < min_needed:
        await send_as_agent(report_channel, MGR_ID, "톡방 만들려면 2명 이상 필요해")
        return

    # 오너+에이전트 1명이면 dm 채널 사용 (없으면 생성)
    if has_owner and len(participants) == 1:
        dm_name = _sanitize_dm_name(participants[0]['name'])
        dm_ch = discord.utils.get(guild.text_channels, name=dm_name)
        if not dm_ch:
            from src.bot.core import _get_category_for_channel, _ensure_category
            from src.core.sync import ensure_unique_channel
            category = await _ensure_category(guild, _get_category_for_channel(dm_name))
            dm_ch, _ = await ensure_unique_channel(guild, dm_name, category or guild.text_channels[0].category)
            CHANNEL_AGENT_MAP[dm_name] = participants[0]["id"]
            AGENT_CHANNEL_MAP[participants[0]["id"]] = dm_name
            db.set_channel_participants(dm_name, [participants[0]["id"]])
        await send_as_agent(report_channel, MGR_ID, f"dm 채널 준비 완료: #{dm_name}")
        return

    names = [p["name"] for p in participants]
    topic = " ".join(topic_parts) if topic_parts else None

    # 오너 포함이면 group, 에이전트끼리면 internal
    if has_owner:
        prefix = "group"
    elif len(participants) == 2:
        prefix = "internal-dm"
    else:
        prefix = "internal-group"
    ch_name = f"{prefix}-{'-'.join(names)}"

    # 반대 순서 이름도 체크
    if len(names) == 2:
        ch_name_alt = f"{prefix}-{names[1]}-{names[0]}"
        existing = discord.utils.get(guild.text_channels, name=ch_name) or \
                   discord.utils.get(guild.text_channels, name=ch_name_alt)
        if existing:
            ch_name = existing.name
    else:
        existing = discord.utils.get(guild.text_channels, name=ch_name)

    if existing:
        # 유저에게 메시지 X (chain 반복 시 spam 됨). 시스템 로그만.
        log_writer.system(f"[create_room] 이미 존재: #{ch_name} (skip)")
        return

    # (existing 없을 때만 여기로 내려와서 생성 + 이벤트 로그)

    # 카테고리 매핑: group-* → glimi-group, internal-* → glimi-internal-* 등.
    # 이전엔 "glimi" 로 하드코딩돼서 모든 그룹/내부 채널이 같은 기본 카테고리로 들어가는 회귀.
    from src.bot.core import _get_category_for_channel, _ensure_category
    from src.core.sync import ensure_unique_channel
    category = await _ensure_category(guild, _get_category_for_channel(ch_name))
    new_ch, _ = await ensure_unique_channel(
        guild, ch_name, category or guild.text_channels[0].category
    )

    # 참여자 등록 (메모리 + DB)
    participant_ids = [p["id"] for p in participants]
    GROUP_PARTICIPANTS[ch_name] = participant_ids
    db.set_channel_participants(ch_name, participant_ids)

    await send_as_agent(report_channel, MGR_ID, f"톡방 만들었어: #{ch_name}")
    log.info(f"[유나CMD] 톡방 생성: {ch_name}")
    # 이벤트 로그 — 채널 생성 (참여자 이름 목록)
    try:
        kind = "단톡방생성" if has_owner else ("비밀톡방생성" if prefix.startswith("internal-") else "톡방생성")
        participant_names = ["owner" if has_owner else None] + [p["name"] for p in participants]
        participant_names = [x for x in participant_names if x]
        db.log_event(kind, participant_names,
                     f"#{ch_name} 생성" + (f" (주제: {topic})" if topic else ""),
                     impact="긍정")
    except Exception:
        pass

    # internal 채널이면 자동으로 대화 시작
    if ch_name.startswith("internal-"):
        async def send_fn(agent_id: str, message: str):
            await send_as_agent(new_ch, agent_id, message)

        context = topic if topic else "자연스럽게 대화 시작"
        asyncio.create_task(_run_and_report_yuna(
            report_channel, ch_name, participant_ids, send_fn, context
        ))


async def yuna_start_conversation(report_channel, args_str, guild):
    """유나가 에이전트간 자동 대화 시작"""
    agents_db = db.list_agents()
    agent_names = {a["name"]: a for a in agents_db}

    tokens = args_str.split()
    participants = []
    context_parts = []
    for t in tokens:
        if t in agent_names:
            participants.append(agent_names[t])
        else:
            # 부분 매칭
            matched = next((a for name, a in agent_names.items() if t in name), None)
            if matched and matched not in participants:
                participants.append(matched)
            else:
                context_parts.append(t)

    if len(participants) < 2:
        await send_as_agent(report_channel, MGR_ID, "대화시키려면 2명 이상 필요해")
        return

    names = [p["name"] for p in participants]
    participant_ids = [p["id"] for p in participants]
    context = " ".join(context_parts) if context_parts else ""
    prefix = "internal-dm" if len(participants) == 2 else "internal-group"
    ch_name = f"{prefix}-{'-'.join(names)}"

    from src.bot.core import _get_category_for_channel, _ensure_category
    category = await _ensure_category(guild, _get_category_for_channel(ch_name))
    # 기존 채널 검색 (이름 순서 반대도 체크)
    target_ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not target_ch and len(names) == 2:
        alt = f"{prefix}-{names[1]}-{names[0]}"
        target_ch = discord.utils.get(guild.text_channels, name=alt)
        if target_ch:
            ch_name = alt
    if not target_ch:
        from src.core.sync import ensure_unique_channel
        target_ch, _ = await ensure_unique_channel(
            guild, ch_name, category or guild.text_channels[0].category
        )

    # 참여자 등록 (메모리 + DB)
    GROUP_PARTICIPANTS[ch_name] = participant_ids
    db.set_channel_participants(ch_name, participant_ids)

    async def send_fn(agent_id: str, message: str):
        await send_as_agent(target_ch, agent_id, message)

    _bot_state._daily_social_count += 1
    asyncio.create_task(_run_and_report_yuna(
        report_channel, ch_name, participant_ids, send_fn, context
    ))
    log.info(f"[유나CMD] 대화 시작: {ch_name} (자율대화 {_bot_state._daily_social_count}/{DAILY_SOCIAL_LIMIT})")


async def _run_and_report_yuna(report_ch, ch_name, participant_ids, send_fn, context):
    """자동 대화 실행 후 유나가 판단 — 오너에게 알릴 게 있으면 후속 트리거"""
    try:
        state = await start_conversation(ch_name, participant_ids, send_fn, context=context)
        names = [runtime.get_agent_name(aid) for aid in participant_ids]

        # 최근 대화 요약 가져오기
        recent = db.get_recent_messages(ch_name, limit=5)
        preview = ""
        if recent:
            preview = "\n".join(f"  {runtime.get_agent_name(r['speaker'])}: {r['message'][:50]}" for r in recent[-3:])

        # 유나에게 보고 + 후속 판단 (강제 CMD는 금지, 대화 트리거는 허용)
        from src.core.profile import get_owner_call_name as _get_oc
        from src.core.prompts.en.mgr_notifications import conversation_report_prompt
        oc = _get_oc() or "오너"
        report_prompt = conversation_report_prompt(
            names=names, channel=ch_name, turn_count=state.turn_count,
            preview=preview, oc=oc,
        )

        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(MGR_ID, "mgr-dashboard", report_prompt, log_user_message=False)
        )
        if responses and report_ch.guild:
            responses = await parse_and_execute_actions(report_ch, responses, report_ch.guild)
        for resp in responses:
            for part in _split_for_chat(resp):
                await send_as_agent(report_ch, MGR_ID, part)
                await asyncio.sleep(0.3)

    except Exception as e:
        await send_as_agent(report_ch, MGR_ID, f"대화 오류: {str(e)[:80]}")


async def yuna_invite_owner(report_channel, args_str, guild):
    """유나가 오너를 특정 채널로 초대 (알림)"""
    ch_name = args_str.strip()
    target_ch = discord.utils.get(guild.text_channels, name=ch_name)

    if not target_ch:
        log_writer.system(f"[not_found] kind=channel name={ch_name}")
        return

    # mgr-dashboard에 오너한테 알림
    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    notify_ch = mgr_ch or report_channel

    from src.core.profile import get_owner_call_name as _get_oc
    oc = _get_oc() or "오너"
    await send_as_agent(notify_ch, MGR_ID,
        f"{oc}, #{ch_name} 에서 얘기 중이야. 와서 같이 얘기해!")

    # 해당 채널에도 안내
    await send_as_agent(target_ch, MGR_ID, f"{oc} 부를게~")
    log.info(f"[유나CMD] 오너 초대: {ch_name}")


async def yuna_change_emotion(report_channel, args_str):
    """유나가 에이전트 감정 변경"""
    parts = args_str.split()
    if len(parts) < 3:
        return

    agent_name, emotion = parts[0], parts[1]
    try:
        intensity = int(parts[2])
    except ValueError:
        return

    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)
    if not target:
        return

    intensity = max(1, min(10, intensity))
    db.update_emotion(target["id"], emotion, intensity)
    runtime.refresh_agent(target["id"])
    log.info(f"[유나CMD] 감정 변경: {agent_name} → {emotion}({intensity})")


# ── 디스코드 채널 관리 ───────────────────────────────────


async def yuna_delete_channel(report_channel, args_str, guild):
    """유나가 채널 삭제"""
    ch_name = args_str.strip()
    target_ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not target_ch:
        log_writer.system(f"[not_found] kind=channel name={ch_name}")
        return

    # 보호: dm- 채널과 mgr- 채널은 삭제 방지
    if ch_name.startswith("dm-") or ch_name.startswith("mgr-"):
        await send_as_agent(report_channel, MGR_ID, f"#{ch_name}은 핵심 채널이라 삭제 못 해")
        return

    stop_conversation(ch_name)
    GROUP_PARTICIPANTS.pop(ch_name, None)
    await target_ch.delete(reason="유나 관리자 삭제")
    await send_as_agent(report_channel, MGR_ID, f"#{ch_name} 삭제 완료")
    log.info(f"[유나CMD] 채널 삭제: {ch_name}")


async def yuna_rename_channel(report_channel, args_str, guild):
    """유나가 채널 이름 변경 — '기존이름 새이름'"""
    parts = args_str.split()
    if len(parts) < 2:
        await send_as_agent(report_channel, MGR_ID, "rename_channel 인자 부족 — old_name/new_name 필요")
        return

    old_name, new_name = parts[0], parts[1]
    target_ch = discord.utils.get(guild.text_channels, name=old_name)
    if not target_ch:
        log_writer.system(f"[not_found] kind=channel name={old_name}")
        return

    # GROUP_PARTICIPANTS 키 갱신
    if old_name in GROUP_PARTICIPANTS:
        GROUP_PARTICIPANTS[new_name] = GROUP_PARTICIPANTS.pop(old_name)

    await target_ch.edit(name=new_name)
    await send_as_agent(report_channel, MGR_ID, f"#{old_name} → #{new_name} 변경 완료")
    log.info(f"[유나CMD] 채널 이름 변경: {old_name} → {new_name}")


async def yuna_set_channel_topic(report_channel, args_str, guild):
    """유나가 채널 토픽 설정 — '채널명 토픽내용'"""
    parts = args_str.split(None, 1)
    if len(parts) < 2:
        await send_as_agent(report_channel, MGR_ID, "set_topic 인자 부족 — channel/topic 필요")
        return

    ch_name, topic = parts[0], parts[1]
    target_ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not target_ch:
        log_writer.system(f"[not_found] kind=channel name={ch_name}")
        return

    await target_ch.edit(topic=topic)
    await send_as_agent(report_channel, MGR_ID, f"#{ch_name} 토픽 설정 완료")
    log.info(f"[유나CMD] 채널 토픽: {ch_name} → {topic}")


# ── 프로필/관계 관리 ─────────────────────────────────────

# 프로필 수정 중복 방지 — (이름, 필드) → (값, 시각)
_recent_profile_edits: dict[tuple[str, str], tuple[str, float]] = {}
_PROFILE_EDIT_DEDUP_SECONDS = 30  # 30초 내 동일 수정 무시


async def yuna_edit_profile(report_channel, args_str):
    """유나가 에이전트 프로필 수정 — '이름 필드경로 값'
    예: 최서연 personality.traits.0 소심한
    예: 은하윤 daily_life.routine 학교→도서관→집
    """
    parts = args_str.split(None, 2)
    if len(parts) < 3:
        await send_as_agent(report_channel, MGR_ID, "update_profile 인자 부족 — name/field/value 필요")
        return

    agent_name, field_path, value = parts[0], parts[1], parts[2]

    # 중복 수정 방지 — 같은 대상+필드에 같은 값을 짧은 시간 내 재실행 차단
    import time as _time
    dedup_key = (agent_name, field_path)
    prev = _recent_profile_edits.get(dedup_key)
    now = _time.time()
    if prev and prev[0] == value and (now - prev[1]) < _PROFILE_EDIT_DEDUP_SECONDS:
        log_writer.system(f"[프로필] 중복 수정 스킵: {agent_name}.{field_path} → {value}")
        return
    _recent_profile_edits[dedup_key] = (value, now)

    # 에이전트에서 먼저 검색
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if target:
        profile = load_profile(target["id"])
        if not profile:
            log_writer.system(f"[프로필] {agent_name} 프로필 로드 실패")
            return
    else:
        # 유저(오너)에서 검색
        conn = db.get_conn()
        user = conn.execute("SELECT * FROM users WHERE name LIKE ?", (f"%{agent_name}%",)).fetchone()
        conn.close()
        if user:
            await _edit_user_profile(report_channel, dict(user), field_path, value)
            return
        log_writer.system(f"[프로필] '{agent_name}' 찾을 수 없음 (에이전트/유저 모두 미매칭)")
        return

    profile = load_profile(target["id"])

    # 필드 경로 탐색 + 수정
    keys = field_path.split(".")
    obj = profile
    try:
        for key in keys[:-1]:
            if key.isdigit():
                obj = obj[int(key)]
            else:
                obj = obj[key]

        last_key = keys[-1]
        if last_key.isdigit():
            obj[int(last_key)] = value
        else:
            obj[last_key] = value

        from src.core.profile import save_profile
        save_profile(profile)
        runtime.refresh_agent(target["id"])

        await send_as_agent(report_channel, MGR_ID,
            f"{agent_name} 프로필 수정 완료: {field_path} → {value}")
        log.info(f"[유나CMD] 프로필 수정: {agent_name}.{field_path} = {value}")

    except (KeyError, IndexError, TypeError) as e:
        log_writer.system(f"[프로필] 수정 실패: {field_path} 경로 오류 ({str(e)[:40]})")


def _values_equivalent(a: str, b: str) -> bool:
    """두 값이 의미상 같은지. 중복 프로필 수정 필터.

    룰:
      1) exact match → True
      2) 한쪽이 비어있으면 False (새 값은 저장)
      3) 토큰 기반: subset(신값 ⊆ 현재값) → True — 정보 손실 방지
      4) jaccard ≥ 0.6 → True — 단순 재서술

    예: 현재 '게임, 영화 감상' + 신 '게임, 영화' → subset True → skip
        현재 '게임, 영화' + 신 '게임, 영화 감상' → jaccard 2/3=0.67 ≥ 0.6 True → skip
        (둘 다 skip — hobby 같은 필드의 미세 재조정 루프 방지)"""
    if a is None or b is None:
        return a == b
    a_str, b_str = str(a).strip(), str(b).strip()
    if a_str == b_str:
        return True
    if not a_str or not b_str:
        return False
    import re as _re2
    atoks = {t for t in _re2.split(r'[,\s/·]+', a_str.lower()) if t}
    btoks = {t for t in _re2.split(r'[,\s/·]+', b_str.lower()) if t}
    if not atoks or not btoks:
        return False
    # 신값(b)이 현재값(a)의 subset → 정보 줄어듬 스킵
    if btoks.issubset(atoks):
        return True
    inter = atoks & btoks
    union = atoks | btoks
    return (len(inter) / len(union)) >= 0.6


async def _edit_user_profile(report_channel, user: dict, field_path: str, value: str):
    """유저(오너) 프로필 필드 수정"""
    import json as _json
    user_id = user["id"]
    user_name = user.get("name", "?")

    # 단순 필드 (users 테이블 직접 컬럼)
    simple_fields = {"name", "age", "birth_year", "mbti", "enneagram", "background"}
    # JSON blob 필드
    json_fields = {"personality", "appearance", "daily_life", "speech"}

    from src.core.profile import invalidate_cache as _invalidate_profile_cache

    def _refresh_active_agents():
        """유저 프로필은 모든 에이전트 system prompt 에 들어가므로 활성 에이전트 전부 재빌드.
        안 하면 runtime._active_agents 에 박힌 옛날 system prompt 계속 사용 → 재질문 회귀."""
        try:
            from src.core.runtime import runtime as _runtime
            for aid in list(_runtime._active_agents.keys()):
                _runtime.refresh_agent(aid)
        except Exception:
            pass

    if field_path in simple_fields:
        conn = db.get_conn()
        cur = conn.execute(f"SELECT {field_path} FROM users WHERE id = ?", (user_id,)).fetchone()
        current = cur[0] if cur else None
        if _values_equivalent(current, value):
            conn.close()
            log_writer.system(f"[프로필] {user_name}.{field_path} 이미 '{current}' ≈ '{value}' — 저장 스킵")
            return
        conn.execute(f"UPDATE users SET {field_path} = ? WHERE id = ?", (value, user_id))
        conn.commit()
        conn.close()
        _invalidate_profile_cache()  # 유저 프로필 캐시/요약 갱신
        _refresh_active_agents()     # 활성 에이전트 system prompt 재빌드 → 다음 응답부터 새 값 반영
        log_writer.system(f"[프로필] {user_name} 수정: {field_path} → {value}")
        return

    # JSON 필드 — dot 있으면 하위 키, 없으면 top-level 통째로 저장
    parts = field_path.split(".", 1)
    if parts[0] in json_fields:
        conn = db.get_conn()
        if len(parts) == 2:
            # speech.style → speech 컬럼의 {"style": value}
            raw = conn.execute(f"SELECT {parts[0]} FROM users WHERE id = ?", (user_id,)).fetchone()
            blob = {}
            if raw and raw[0]:
                try:
                    blob = _json.loads(raw[0]) if isinstance(raw[0], str) else raw[0]
                except Exception:
                    blob = {}
            if _values_equivalent(blob.get(parts[1]), value):
                conn.close()
                log_writer.system(f"[프로필] {user_name}.{field_path} 이미 '{blob.get(parts[1])}' ≈ '{value}' — 저장 스킵")
                return
            blob[parts[1]] = value
            conn.execute(f"UPDATE users SET {parts[0]} = ? WHERE id = ?", (_json.dumps(blob, ensure_ascii=False), user_id))
        else:
            # speech → speech 컬럼 통째로
            if value.startswith("{"):
                conn.execute(f"UPDATE users SET {field_path} = ? WHERE id = ?", (value, user_id))
            else:
                conn.execute(f"UPDATE users SET {field_path} = ? WHERE id = ?", (_json.dumps({"style": value}, ensure_ascii=False), user_id))
        conn.commit()
        conn.close()
        _invalidate_profile_cache()
        _refresh_active_agents()
        log_writer.system(f"[프로필] {user_name} 수정: {field_path} → {value}")
        return

    log_writer.system(f"[프로필] {user_name} 필드 '{field_path}' 찾을 수 없음 (무시)")


async def yuna_edit_relationship(report_channel, args_str, caller_agent_id: str = ""):
    """유나가 관계 수정 — '이름A 이름B 필드 값'
    예: 은하윤 최지수 intimacy +10
    예: 은하윤 최지수 type 절친

    허용 필드: intimacy / affection (intimacy 의 alias) / type / dynamics
    Self-modification 금지: caller (mgr/creator) 가 자기 자신의 관계를 직접 올리는 호출은 거부.
    """
    parts = args_str.split()
    if len(parts) < 4:
        await send_as_agent(report_channel, MGR_ID, "update_relationship 인자 부족 — agent_a/agent_b/field/value 필요")
        return {"ok": False, "error": "args 부족"}

    name_a, name_b, field, value = parts[0], parts[1], parts[2], " ".join(parts[3:])

    agents = db.list_agents()
    agent_by_name = {a["name"]: a for a in agents}
    agent_by_name[get_user_name()] = {"id": get_user_id(), "name": get_user_name()}

    a = agent_by_name.get(name_a)
    b = agent_by_name.get(name_b)
    if not a or not b:
        await send_as_agent(report_channel, MGR_ID, f"에이전트를 찾을 수 없어: {name_a}, {name_b}")
        return {"ok": False, "error": "agent not found"}

    # ── Self-modification guard ──
    # mgr/creator 가 자기 자신을 한쪽 끝으로 두고 호감도/intimacy 를 직접 올리는 호출은 거부.
    # 회귀: 유나가 사용자 명령에 휘둘려 자기↔owner 호감도 100 으로 set 하는 시도 (LLM placebo).
    # 실제 호감도 변화는 자연 누적 (메모리 추출 시 +1 배치) 으로만 일어나야 함.
    if caller_agent_id:
        caller_agent = db.get_agent(caller_agent_id)
        caller_type = (caller_agent or {}).get("type", "")
        if caller_type in ("mgr", "creator"):
            if a["id"] == caller_agent_id or b["id"] == caller_agent_id:
                if field in ("intimacy", "affection"):
                    log_writer.system(
                        f"[권한거부] {caller_agent_id}({caller_type}) 가 자기 자신의 관계 호감도 직접 수정 시도 차단: "
                        f"{name_a}↔{name_b} {field}={value}"
                    )
                    await send_as_agent(report_channel, MGR_ID,
                        "내 호감도/친밀도는 내가 직접 올리거나 내릴 수 없어. "
                        "관계는 자연스러운 대화로만 쌓여."
                    )
                    return {"ok": False, "error": "self_modification_denied",
                            "rule": "mgr/creator cannot edit own affection/intimacy"}

    # ── Field 정규화 + 분기 ──
    field_norm = field.lower()
    if field_norm in ("intimacy", "affection", "호감도", "친밀도"):
        # 자동 row 생성 — 없으면 INSERT
        existing = db.get_relationship(a["id"], b["id"]) or db.get_relationship(b["id"], a["id"])
        if not existing:
            db.add_relationship(a["id"], b["id"], rel_type="", intimacy=db.INTIMACY_SCALE_DEFAULT)
            existing = db.get_relationship(a["id"], b["id"])
        if value.startswith("+") or value.startswith("-"):
            delta = int(value)
            db.update_intimacy(a["id"], b["id"], delta)
            await send_as_agent(report_channel, MGR_ID,
                f"{name_a}↔{name_b} 호감도 {value} 변경")
            return {"ok": True, "delta": delta}
        score = max(0, min(100, int(value)))
        conn = db.get_conn()
        # 양방향 모두 있을 수 있으니 둘 다 UPDATE 시도
        for ax, bx in [(a["id"], b["id"]), (b["id"], a["id"])]:
            conn.execute(
                "UPDATE relationships SET intimacy_score=?, updated_at=? WHERE agent_a=? AND agent_b=?",
                (score, now_utc_iso(), ax, bx),
            )
        conn.commit()
        conn.close()
        await send_as_agent(report_channel, MGR_ID,
            f"{name_a}↔{name_b} 호감도 → {score}")
        return {"ok": True, "score": score}

    elif field_norm == "type":
        conn = db.get_conn()
        existing = conn.execute(
            "SELECT 1 FROM relationships WHERE (agent_a=? AND agent_b=?) OR (agent_a=? AND agent_b=?)",
            (a["id"], b["id"], b["id"], a["id"]),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO relationships (agent_a, agent_b, type, intimacy_score, dynamics, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (a["id"], b["id"], value, 50, "", now_utc_iso()),
            )
        else:
            for ax, bx in [(a["id"], b["id"]), (b["id"], a["id"])]:
                conn.execute(
                    "UPDATE relationships SET type=?, updated_at=? WHERE agent_a=? AND agent_b=?",
                    (value, now_utc_iso(), ax, bx),
                )
        conn.commit()
        conn.close()
        await send_as_agent(report_channel, MGR_ID,
            f"{name_a}↔{name_b} 관계 → {value}")
        return {"ok": True, "type": value}

    elif field_norm == "dynamics":
        conn = db.get_conn()
        existing = conn.execute(
            "SELECT 1 FROM relationships WHERE (agent_a=? AND agent_b=?) OR (agent_a=? AND agent_b=?)",
            (a["id"], b["id"], b["id"], a["id"]),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO relationships (agent_a, agent_b, type, intimacy_score, dynamics, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (a["id"], b["id"], "", 50, value, now_utc_iso()),
            )
        else:
            for ax, bx in [(a["id"], b["id"]), (b["id"], a["id"])]:
                conn.execute(
                    "UPDATE relationships SET dynamics=?, updated_at=? WHERE agent_a=? AND agent_b=?",
                    (value, now_utc_iso(), ax, bx),
                )
        conn.commit()
        conn.close()
        await send_as_agent(report_channel, MGR_ID,
            f"{name_a}↔{name_b} 역학 → {value}")
        return {"ok": True, "dynamics": value}

    else:
        # Unknown field — 명시적 fail
        log_writer.system(
            f"[update_relationship] 알 수 없는 필드 '{field}' (caller={caller_agent_id}) — DB 변경 0"
        )
        await send_as_agent(report_channel, MGR_ID,
            f"관계 필드 '{field}' 모름. 사용 가능: intimacy(=affection) / type / dynamics")
        return {"ok": False, "error": "unknown_field", "field": field,
                "allowed": ["intimacy", "affection", "type", "dynamics"]}

    log.info(f"[유나CMD] 관계 수정: {name_a}↔{name_b} {field}={value}")


# ── DB 정리 / 디스코드 메시지 관리 ────────────────────────


async def yuna_wipe_channel(report_channel, args_str, guild):
    """채널 통째로 날리기 — DB(대화+메모리) + 디스코드 채널 삭제
    형식: 채널명 [keep_discord]
    keep_discord 붙이면 디스코드 채널은 유지하고 DB만 삭제
    """
    parts = args_str.split()
    ch_name = parts[0] if parts else ""
    keep_discord = "keep_discord" in args_str

    if not ch_name:
        await send_as_agent(report_channel, MGR_ID, "채널명 필요해")
        return

    if ch_name.startswith("mgr-"):
        await send_as_agent(report_channel, MGR_ID, f"#{ch_name}은 관리 채널이라 초기화 못 해")
        return

    result = db.delete_channel_data(ch_name)
    GROUP_PARTICIPANTS.pop(ch_name, None)

    msg = f"#{ch_name} DB 삭제 완료 (대화 {result['messages_deleted']}건, 메모리 {result['memories_deleted']}건)"

    if not keep_discord:
        target_ch = discord.utils.get(guild.text_channels, name=ch_name)
        if target_ch:
            stop_conversation(ch_name)
            await target_ch.delete(reason="유나 채널 초기화")
            msg += " + 디스코드 채널 삭제"

    await send_as_agent(report_channel, MGR_ID, msg)
    log.info(f"[유나CMD] 채널 초기화: {ch_name}")


async def yuna_delete_messages(report_channel, args_str):
    """대화 이력 선택 삭제
    형식:
      채널 채널명 — 해당 채널 전체 대화 삭제 (메모리 유지)
      화자 채널명 이름 — 특정 채널에서 특정 화자 메시지만 삭제
      키워드 검색어 — 전체에서 키워드 포함 메시지 삭제
      키워드 검색어 채널명 — 특정 채널에서 키워드 포함 메시지 삭제
    """
    parts = args_str.split()
    if len(parts) < 2:
        await send_as_agent(report_channel, MGR_ID, "clear_messages 인자 부족 — mode=channel/keyword 와 대응 인자 필요")
        return

    mode = parts[0]

    if mode == "채널":
        ch_name = parts[1]
        result = db.delete_channel_data(ch_name)
        await send_as_agent(report_channel, MGR_ID,
            f"#{ch_name} 대화 {result['messages_deleted']}건 + 메모리 {result['memories_deleted']}건 삭제")

    elif mode == "화자":
        if len(parts) < 3:
            await send_as_agent(report_channel, MGR_ID, "clear_messages mode=speaker 는 channel 과 speaker_name 필요")
            return
        ch_name, agent_name = parts[1], parts[2]
        agents = db.list_agents()
        target = next((a for a in agents if a["name"] == agent_name), None)
        speaker_id = target["id"] if target else (get_user_id() if agent_name == get_user_name() else None)
        if not speaker_id:
            log_writer.system(f"[not_found] kind=agent name={agent_name}")
            return
        count = db.delete_messages_by_speaker(ch_name, speaker_id)
        await send_as_agent(report_channel, MGR_ID, f"#{ch_name}에서 {agent_name} 메시지 {count}건 삭제")

    elif mode == "키워드":
        # 마지막 단어가 채널명(dm-/group-/internal-/mgr)이면 채널 지정
        remaining = parts[1:]
        ch_name = None
        if remaining and any(remaining[-1].startswith(p) for p in ("dm-", "group-", "internal-dm-", "internal-group-", "mgr")):
            ch_name = remaining[-1]
            remaining = remaining[:-1]
        keyword = " ".join(remaining)
        if not keyword:
            await send_as_agent(report_channel, MGR_ID, "키워드가 필요해")
            return
        count = db.delete_messages_by_keyword(keyword, channel=ch_name)
        scope = f"#{ch_name}" if ch_name else "전체"
        await send_as_agent(report_channel, MGR_ID, f"{scope}에서 '{keyword}' 포함 메시지 {count}건 삭제")

    else:
        await send_as_agent(report_channel, MGR_ID, "모드: 채널/화자/키워드")

    log.info(f"[유나CMD] 대화 삭제: {args_str}")


async def yuna_wipe_agent(report_channel, args_str):
    """에이전트 전체 데이터 초기화 (대화+메모리+이벤트)"""
    agent_name = args_str.strip()
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)
    if not target:
        log_writer.system(f"[not_found] kind=agent name={agent_name}")
        return

    result = db.delete_agent_all_data(target["id"])
    await send_as_agent(report_channel, MGR_ID,
        f"{agent_name} 데이터 전체 삭제: 대화 {result['messages']}건, 메모리 {result['memories']}건, 이벤트 {result['events']}건")
    log.info(f"[유나CMD] 에이전트 초기화: {agent_name}")


async def yuna_purge_messages(report_channel, args_str, guild):
    """디스코드 채널 메시지 일괄 삭제 (봇 메시지 청소용)
    형식: 채널명 개수
    """
    parts = args_str.split()
    ch_name = parts[0] if parts else ""
    count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 50
    count = min(count, 200)

    target_ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not target_ch:
        log_writer.system(f"[not_found] kind=channel name={ch_name}")
        return

    try:
        # purge는 14일 이내만 가능 — 실패하면 개별 삭제 시도
        deleted = await target_ch.purge(limit=count)
        deleted_count = len(deleted)

        # purge로 못 지운 오래된 메시지가 있을 수 있음
        if deleted_count < count:
            remaining = count - deleted_count
            async for msg in target_ch.history(limit=remaining):
                try:
                    await msg.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.5)  # rate limit
                except Exception:
                    pass

        await send_as_agent(report_channel, MGR_ID, f"#{ch_name} 디스코드 메시지 {deleted_count}개 삭제")
    except discord.errors.Forbidden:
        await send_as_agent(report_channel, MGR_ID, "메시지 삭제 권한이 없어")
    except Exception as e:
        await send_as_agent(report_channel, MGR_ID, f"메시지 삭제 실패: {str(e)[:60]}")

    log.info(f"[유나CMD] 디스코드 메시지 청소: {ch_name} {count}개")


async def yuna_restore_discord(report_channel, args_str, guild):
    """DB 메시지를 디스코드에 재전송 (DB 변경 없음)
    형식: 채널명
    """
    ch_name = args_str.strip()
    if not ch_name:
        await send_as_agent(report_channel, MGR_ID, "채널명을 알려줘")
        return

    target_ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not target_ch:
        log_writer.system(f"[not_found] kind=channel name={ch_name}")
        return

    messages = db.get_all_messages(ch_name)
    if not messages:
        await send_as_agent(report_channel, MGR_ID, f"#{ch_name}에 DB 메시지가 없어")
        return

    await send_as_agent(report_channel, MGR_ID, f"#{ch_name} 디코 복구 시작할게 ({len(messages)}개)")

    agents_db = db.list_agents()
    agent_id_by_name = {a["name"]: a["id"] for a in agents_db}

    sent = 0
    for msg in messages:
        speaker = msg["speaker"]
        text = (msg["message"] or "").strip()
        if not text:
            continue

        try:
            if speaker == get_user_id() or speaker == get_user_name():
                # 오너 메시지: 프로필 이미지 없이 이름만
                webhook = await _get_plain_webhook(target_ch)
                await webhook.send(content=text, username=get_user_name())
            else:
                # 에이전트 메시지: 기존 웹훅(아바타+이름) 사용
                agent_id = speaker if speaker.startswith("agent-") else agent_id_by_name.get(speaker)
                if agent_id:
                    await send_as_agent(target_ch, agent_id, text)
                else:
                    # ID 매핑 실패 시 이름으로 전송
                    webhook = await _get_plain_webhook(target_ch)
                    await webhook.send(content=text, username=speaker)
            sent += 1
        except Exception as e:
            log.warning(f"[디코복구] 전송 실패: {e}")

        # 레이트 리밋 방지
        await asyncio.sleep(0.5)

    await send_as_agent(report_channel, MGR_ID, f"#{ch_name} 디코 복구 완료 ({sent}/{len(messages)}개)")
    log.info(f"[유나CMD] 디코 복구: {ch_name} {sent}/{len(messages)}개")


# ── ACTION 승인 / 강제 지시 ──────────────────────────────


async def yuna_approve_action(report_channel, args_str, guild):
    """ACTION 승인 — DM: 원본 메시지 전달 / 톡방: 생성 후 첫 메시지 전송"""
    # 타입 + 발신자ID 파싱
    parts = args_str.split(None, 2)
    if len(parts) < 3:
        await send_as_agent(report_channel, MGR_ID, "형식이 맞지 않아")
        return

    action_type = parts[0].upper()
    sender_id = parts[1]
    rest = parts[2]
    sender_name = runtime.get_agent_name(sender_id)
    agents_all = db.list_agents()
    agent_by_name = {a["name"]: a for a in agents_all}

    if action_type == "DM":
        # rest = "대상이름 메시지내용"
        dm_parts = rest.split(None, 1)
        if len(dm_parts) < 2:
            await send_as_agent(report_channel, MGR_ID, "DM 승인 인자 부족 — target_name/message 필요")
            return
        target_name, message = dm_parts

        target = agent_by_name.get(target_name)
        if not target:
            log_writer.system(f"[not_found] kind=agent name={target_name}")
            return
        target_id = target["id"]

        # internal-dm 채널 찾기/생성 — 유나 우선 정렬 convention
        from src.bot import internal_dm_channel_name
        ch_name = internal_dm_channel_name(sender_name, target_name)
        ch_name_alt = f"internal-dm-{target_name}-{sender_name}"  # 구 order 호환
        ch_name_alt2 = f"internal-dm-{sender_name}-{target_name}"  # 구 order 호환
        target_ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_ch:
            target_ch = discord.utils.get(guild.text_channels, name=ch_name_alt) \
                     or discord.utils.get(guild.text_channels, name=ch_name_alt2)
        if not target_ch:
            from src.core.sync import ensure_unique_channel
            category = discord.utils.get(guild.categories, name="internal") or \
                       (guild.categories[0] if guild.categories else None)
            target_ch, _ = await ensure_unique_channel(guild, ch_name, category)
            db.set_channel_participants(ch_name, [sender_id, target_id])

        # 원본 메시지를 sender로 전송
        await send_as_agent(target_ch, sender_id, message)
        db.log_message(target_ch.name, sender_id, message)

        # 대상 에이전트가 발신자의 메시지에 응답 (에이전트간 대화)
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_agent_to_agent(
                target_id, sender_id, target_ch.name,
                context=f"{sender_name}이(가) 말했어: {message}"
            )
        )
        for resp in responses:
            await send_as_agent(target_ch, target_id, resp)
            await asyncio.sleep(0.5)

        await send_as_agent(report_channel, MGR_ID,
            f"✓ {sender_name} → {target_name} DM 전달 완료 (#{target_ch.name})")
        log_writer.system(f"✓ ACTION 승인: {sender_name} → {target_name} DM")

    elif action_type == "톡방":
        # rest = "이름1 이름2 ... | 첫메시지"
        if "|" in rest:
            room_info, first_msg = rest.split("|", 1)
            room_info = room_info.strip()
            first_msg = first_msg.strip()
        else:
            room_info = rest
            first_msg = ""

        # 참여자 파싱 — 발신자 자동 포함
        names_in = room_info.split()
        participants = []
        for n in names_in:
            if n in agent_by_name:
                participants.append(agent_by_name[n])

        # 발신자가 참여자 목록에 없으면 추가
        sender_agent = next((a for a in agents_all if a["id"] == sender_id), None)
        if sender_agent and sender_agent not in participants:
            participants.insert(0, sender_agent)

        if len(participants) < 2:
            await send_as_agent(report_channel, MGR_ID, "톡방은 최소 2명 필요해")
            return

        part_names = [p["name"] for p in participants]
        prefix = "internal-group" if len(part_names) > 2 else "internal-dm"
        ch_name = f"{prefix}-" + "-".join(part_names)
        part_ids = [p["id"] for p in participants]

        # 채널 찾기/생성 — ensure_unique_channel 로 중복 방지
        from src.core.sync import ensure_unique_channel
        category = discord.utils.get(guild.categories, name="group") or \
                   (guild.categories[0] if guild.categories else None)
        target_ch, _ = await ensure_unique_channel(guild, ch_name, category)

        GROUP_PARTICIPANTS[ch_name] = part_ids
        db.set_channel_participants(ch_name, part_ids)

        # 첫 메시지 전송 (발신자 이름으로)
        if first_msg:
            await send_as_agent(target_ch, sender_id, first_msg)
            db.log_message(ch_name, sender_id, first_msg)

        await send_as_agent(report_channel, MGR_ID,
            f"✓ {sender_name} 요청 톡방 생성 완료: #{ch_name} ({', '.join(part_names)})")
        log_writer.system(f"✓ ACTION 승인: {sender_name} 톡방 {ch_name}")

    else:
        await send_as_agent(report_channel, MGR_ID, f"알 수 없는 ACTION 타입: {action_type}")


async def yuna_force_agent(report_channel, args_str, guild):
    """유나가 특정 에이전트에게 강제 지시 — 에이전트는 유나 존재 모름"""
    parts = args_str.split(None, 2)
    if len(parts) < 3:
        await send_as_agent(report_channel, MGR_ID, "형식: 강제 이름 채널명 지시내용")
        return

    agent_name, ch_name, instruction = parts[0], parts[1], parts[2]

    # 에이전트 찾기
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)
    if not target:
        log_writer.system(f"[not_found] kind=agent name={agent_name}")
        return

    agent_id = target["id"]

    # 채널 존재 확인 — 공백 등 비정규화된 이름 fallback (예: 'dm-유키 아스나' ↔ 'dm-유키-아스나')
    if guild:
        target_ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_ch:
            import re as _re
            normalized = _re.sub(r"\s+", "-", ch_name.strip())
            if normalized != ch_name:
                target_ch = discord.utils.get(guild.text_channels, name=normalized)
                if target_ch:
                    log_writer.system(f"[invoke_agent] 채널명 정규화 매칭: '{ch_name}' → '{normalized}'")
                    ch_name = normalized
        if not target_ch:
            log_writer.system(f"[not_found] kind=channel name={ch_name}")
            return

    log_writer.system(f"🔧 유나 강제지시: {agent_name} @ {ch_name} → {instruction[:50]}")

    # generate_response_force 사용 — 유나 존재 노출 없이 시스템 레벨 강제
    loop = asyncio.get_event_loop()
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response_force(agent_id, ch_name, instruction)
    )

    # 응답이 비어있으면 timeout/에러 상황 — target 채널 송출 skip, 유나에게 실패 알림.
    # 과거엔 placeholder ("Claude Code 연결 끊겨있어") 가 target 에 그대로 나가서 몰입 파괴.
    if not responses:
        await send_as_agent(report_channel, MGR_ID,
            f"⚠ {agent_name}한테 강제지시 보냈는데 응답 못 받았어 (#{ch_name}) — 나중에 다시 해볼게")
        return

    # 해당 채널에 에이전트 응답 전송
    if guild:
        for resp in responses:
            await send_as_agent(target_ch, agent_id, resp)
            await asyncio.sleep(0.5)

    await send_as_agent(report_channel, MGR_ID,
        f"✓ {agent_name}한테 강제 지시 완료 (#{ch_name})")


# ── 개발 요청 시스템 ─────────────────────────────────────


def create_dev_request(description: str, requested_by: str) -> None:
    """개발 요청 파일 생성 (dev/pending.json)"""
    with open(DEV_PENDING, "w", encoding="utf-8") as f:
        json.dump({
            "description": description,
            "requested_by": requested_by,
            "timestamp": now_utc_iso(),
        }, f, ensure_ascii=False, indent=2)
    log.info(f"[Dev] 요청 생성 — {description[:50]}")


async def yuna_dev_request(report_channel, args_str, requested_by):
    """유나/오너이 개발 요청 → 봇 종료 트리거"""
    if not args_str.strip():
        await send_as_agent(report_channel, MGR_ID, "개발 요청 내용이 필요해")
        return

    # 이미 종료 대기 중이면 무시 (중복 방지)
    if _bot_state._shutdown_pending:
        await send_as_agent(report_channel, MGR_ID, "이미 개발 요청 처리 중이야~")
        return

    # 이미 pending 요청이 있으면 무시
    if os.path.exists(DEV_PENDING):
        await send_as_agent(report_channel, MGR_ID, "이미 대기 중인 개발 요청이 있어")
        return

    create_dev_request(args_str.strip(), requested_by)

    await send_as_agent(report_channel, MGR_ID,
        "개발 요청 접수! 잠시 종료하고 Opus가 코드 수정할게. 끝나면 돌아올게~")

    await asyncio.sleep(2)

    _bot_state._shutdown_pending = True
    log.info(f"[Dev] 봇 종료 예정 — 개발 요청")
    await bot.close()


async def check_dev_results():
    """봇 시작 시 개발 결과 체크 → 유나가 분석/판단/보고"""
    if not os.path.exists(DEV_RESULT):
        return

    from src.bot.core import get_target_guild
    guild = get_target_guild()
    if not guild:
        return
    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    if not mgr_ch:
        return

    try:
        with open(DEV_RESULT, "r", encoding="utf-8") as f:
            result = json.load(f)

        status = result.get("status", "unknown")
        message = result.get("message", "")
        requested_by = result.get("requested_by", "unknown")

        os.remove(DEV_RESULT)

        # 유나에게 결과 전달 → 유나가 판단해서 보고/재요청
        from src.core.profile import get_owner_call_name as _get_oc
        oc = _get_oc() or "오너"
        dev_report = (
            f"[개발 결과 도착]\n"
            f"상태: {status}\n"
            f"요청자: {requested_by}\n"
            f"결과:\n{message[:2000]}\n\n"
            f"위 개발 결과를 보고 판단해:\n"
            f"1. 성공이면 {oc}한테 뭘 고쳤는지 간결하게 보고해\n"
            f"2. 실패했거나 의도대로 안 됐으면 네가 다시 `request_dev_task` 도구로 재요청해 (원래 요청 + 실패 원인 포함)\n"
            f"3. 네 선에서 판단 불가능한 문제면 {oc}한테 상황 설명하고 어떻게 할지 물어봐"
        )

        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(
                MGR_ID, MGR_CHANNEL, dev_report, log_user_message=False
            )
        )

        # CMD/QUERY 파싱 (유나가 재개발요청 할 수 있도록)
        if responses and guild:
            responses = await parse_and_execute_actions(mgr_ch, responses, guild)

        for resp in responses:
            for part in _split_for_chat(resp):
                await send_as_agent(mgr_ch, MGR_ID, part)
                await asyncio.sleep(0.3 + random.uniform(0, 0.4))

        log.info("[Dev] 결과 보고 완료")

    except Exception as e:
        log.error(f"[Dev] 결과 처리 오류: {e}")


# ── 프로필 파일 관리 (하나 전용) ─────────────────────────


async def _cmd_profile_create(report_channel, json_str):
    """프로필 JSON 파일 생성 (하나 전용)"""
    import json as json_mod
    creator_id = "agent-creator-001"
    try:
        # JSON 추출
        text = json_str.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        profile = json_mod.loads(text)
        if not profile.get("id") or not profile.get("name"):
            await send_as_agent(report_channel, creator_id, "프로필에 id랑 name은 필수야")
            return

        # 중복 생성 차단 — 같은 이름의 persona 이미 있으면 skip.
        # 이전엔 Creator 가 tool chain 속에서 같은 친구를 2번 생성 → 덮어쓰기 → dm 첫 인사 재트리거
        # → 유저에게 "얘가 왜 또 인사해?" (QA #5 회귀: 송지안 00:24 + 00:27 두 번 create).
        existing = db.get_agent_by_name(profile["name"])
        if existing and existing.get("id") != profile["id"] and existing.get("type") == "persona":
            log_writer.system(
                f"[create_agent_profile] 중복 skip: '{profile['name']}' 이미 존재 "
                f"(id={existing['id']})"
            )
            # Creator 에게 조용히 skip 사실만 알림 (유저 채널엔 메시지 X)
            return

        from src.core.profile import save_profile
        save_profile(profile)

        # DB 등록
        agent_type = profile.get("type", "persona")
        db.register_agent(profile["id"], agent_type, profile["name"])

        # 관계 설정 — 페르소나는 무조건 오너와 row 생성 (없으면 default).
        if agent_type == "persona":
            r2o = profile.get("relationship_to_owner")
            if isinstance(r2o, dict):
                rel_type = r2o.get("type") or "친구"
                rel_intimacy = r2o.get("intimacy", db.INTIMACY_SCALE_DEFAULT)
                rel_dynamics = r2o.get("dynamics", "")
            else:
                rel_type = "친구"
                rel_intimacy = db.INTIMACY_SCALE_DEFAULT
                rel_dynamics = ""
            db.add_relationship(
                get_user_id(), profile["id"],
                rel_type,
                intimacy=rel_intimacy,
                dynamics=rel_dynamics,
            )

            # 페르소나간 관계 시드 — Hana 의 relationship_templates 에서 is_owner_relationship=0
            # 항목들을 실제 relationships 테이블에 row 로 materialize.
            # 이전엔 templates 테이블에만 저장 → relationships 비어 있음 → orchestrator 의 페어
            # internal-dm 이 "처음 보는 사이" 로 시작 → 어색·단답·일찍 종료 회귀.
            # 이제 시드 직후 페어 관계 row 가 살아 있어 첫 internal-dm 부터 공통 referent O.
            try:
                rel_templates = profile.get("relationship_templates") or []
                for t in rel_templates:
                    if not isinstance(t, dict):
                        continue
                    if t.get("is_owner_relationship"):
                        continue
                    target_id = t.get("target_id")
                    if not target_id or not db.get_agent(target_id):
                        continue
                    if db.get_relationship(profile["id"], target_id) or db.get_relationship(target_id, profile["id"]):
                        continue
                    inter_intimacy = int(t.get("intimacy", 60))  # 친구 default
                    db.add_relationship(
                        profile["id"], target_id,
                        t.get("rel_type") or "친구",
                        intimacy=inter_intimacy,
                        dynamics=t.get("dynamics") or t.get("note") or "",
                    )
                    log_writer.system(
                        f"[create] 페르소나간 관계 시드: {profile['name']} ↔ {target_id} "
                        f"({t.get('rel_type', '친구')}, {inter_intimacy})"
                    )
            except Exception as e:
                log_writer.system(f"[create] persona-persona 관계 시드 실패: {type(e).__name__}: {e}")

        runtime.activate_agent(profile["id"])
        runtime.refresh_agent("agent-mgr-001")

        # dm 채널 자동 생성 (persona만)
        new_dm_name = None
        if agent_type == "persona" and report_channel.guild:
            dm_name = _sanitize_dm_name(profile['name'])
            from src.bot.core import _get_category_for_channel, _ensure_category
            from src.core.sync import ensure_unique_channel
            cat = await _ensure_category(report_channel.guild, _get_category_for_channel(dm_name))
            _new_ch, was_created = await ensure_unique_channel(report_channel.guild, dm_name, cat)
            if was_created:
                log_writer.system(f"dm 채널 생성: {dm_name}")
            db.set_channel_participants(dm_name, [profile["id"]])
            CHANNEL_AGENT_MAP[dm_name] = profile["id"]
            AGENT_CHANNEL_MAP[profile["id"]] = dm_name
            new_dm_name = dm_name

        # agent_id 는 시스템 로그에만. 유저 채널엔 이름만 (internal ID 노출 시 몰입 깨짐).
        log_writer.system(f"프로필 생성: {profile['name']} ({profile['id']})")

        # 새 친구가 자기 dm 채널에서 자동 인사 — 오너가 들어올 때 침묵 방지
        if new_dm_name and agent_type == "persona":
            import asyncio as _aio
            _aio.create_task(
                _greet_new_persona(
                    report_channel.guild, profile["id"], profile["name"], new_dm_name
                )
            )

    except Exception as e:
        log_writer.system(f"[프로필생성] 실패: {type(e).__name__}: {str(e)[:100]}")
        await send_as_agent(report_channel, creator_id, "프로필 생성에 문제가 있었어... 다시 해볼게")


async def _greet_new_persona(guild, agent_id, agent_name, dm_name):
    """새로 만든 persona 에이전트가 자기 dm 채널에서 오너에게 첫 인사 — 채널만 있고
    침묵하면 오너가 들어와도 뭘 해야 할지 모름. 생성 직후 자연스럽게 인사 주도."""
    import asyncio as _aio
    from src.bot.core import _split_for_chat
    try:
        await _aio.sleep(3)  # 채널 생성 커밋 + UI 반영 여유
        ch = discord.utils.get(guild.text_channels, name=dm_name)
        if not ch:
            log_writer.system(f"[not_found] kind=dm_channel name={dm_name} phase=greet_skip")
            return

        from src.core.profile import get_user_name, get_owner_call_name
        from src.core.prompts.en.persona_events import persona_first_greeting_prompt
        owner_name = get_user_name() or "user"
        call = get_owner_call_name() or owner_name
        prompt = persona_first_greeting_prompt(dm_name=dm_name, call=call)

        loop = _aio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(
                agent_id, dm_name, prompt, log_user_message=False
            )
        )
        sent = 0
        for resp in responses:
            resp = resp.strip()
            if not resp:
                continue
            for part in _split_for_chat(resp):
                await send_as_agent(ch, agent_id, part)
                await _aio.sleep(1)
                sent += 1
        if sent == 0:
            log_writer.system(f"⚠ 새친구 {agent_name} dm 인사 0건 — 응답 비어있음")
        else:
            log_writer.system(f"새친구 {agent_name}({agent_id}) #{dm_name}에서 {sent}건 인사")
    except Exception as e:
        log_writer.system(f"[새친구인사] 실패: {type(e).__name__}: {e}")


async def _cmd_profile_delete(report_channel, args_str):
    """프로필 파일 삭제 (하나 전용)"""
    import os as _os
    creator_id = "agent-creator-001"
    agent_name = args_str.strip()
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name or agent_name in a["name"]), None)

    if not target:
        log_writer.system(f"[not_found] kind=agent name={agent_name}")
        return

    profile_path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "profiles", f"{target['id']}.json")
    if _os.path.exists(profile_path):
        _os.remove(profile_path)

    conn = db.get_conn()
    conn.execute("UPDATE agents SET status = 'archived' WHERE id = ?", (target["id"],))
    conn.commit()
    conn.close()
    from src.core.profile import invalidate_cache
    invalidate_cache(target["id"])
    runtime.refresh_agent("agent-mgr-001")

    await send_as_agent(report_channel, creator_id, f"{target['name']} 프로필 삭제 + 비활성화 완료")
    log_writer.system(f"프로필 삭제: {target['name']} ({target['id']})")


# ── 톡방 요청 감지 ───────────────────────────────────────


async def handle_room_request_detection(
    channel: discord.TextChannel,
    agent_id: str,
    message: str,
    guild: discord.Guild,
):
    """에이전트 메시지에서 톡방 요청 감지 → 유나에게 알림"""
    if not detect_room_request(message):
        return

    agent_name = runtime.get_agent_name(agent_id)
    log.info(f"[감지] 톡방 요청: {agent_name} → '{message[:40]}'")

    # 유나에게 알림 (mgr-dashboard 채널)
    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    if mgr_ch:
        # 유나가 판단해서 행동하도록 알림
        from src.core.prompts.en.mgr_notifications import room_request_notify_prompt
        notify_prompt = room_request_notify_prompt(agent_name=agent_name, message=message)

        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(MGR_ID, MGR_CHANNEL, notify_prompt)
        )

        # 유나 응답에서 CMD 파싱 + 실행
        cleaned = await parse_and_execute_actions(mgr_ch, responses, guild)
        for msg in cleaned:
            await send_as_agent(mgr_ch, MGR_ID, msg)
            await asyncio.sleep(0.5)


async def _apply_sample_profile_image(report_channel, args_str, guild, caller_agent_id: str = ""):
    """샘플 프로필 이미지를 에이전트에 적용 (기본 + -full 같이 복사)"""
    import shutil
    parts = args_str.split(None, 1)
    agent_name = _resolve_agent_name(parts[0]) if parts else ""
    sample_file = parts[1].strip() if len(parts) > 1 else ""

    # JSON 파싱 시도
    if args_str.strip().startswith("{"):
        try:
            import json as _json
            data = _json.loads(args_str)
            agent_name = _resolve_agent_name(data.get("name", ""))
            sample_file = data.get("sample", "") or data.get("profile_image_filename", "") or data.get("avatar_filename", "")
        except Exception:
            pass

    if not agent_name or not sample_file:
        await send_as_agent(report_channel, MGR_ID, "에이전트 이름이랑 샘플 파일명이 필요해")
        return

    # 에이전트 찾기
    target = None
    for a in db.list_agents():
        if a["name"] == agent_name:
            target = a
            break
    if not target:
        log_writer.system(f"[not_found] kind=agent name={agent_name}")
        return

    # 샘플 파일 확인
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sample_dir = os.path.join(project_root, "assets", "sample_profile_images")
    sample_path = os.path.join(sample_dir, sample_file)
    if not os.path.exists(sample_path):
        log_writer.system(f"[not_found] kind=sample name={sample_file}")
        return

    # 커뮤니티 프로필 이미지 디렉토리에 복사 (agent_id.png + agent_id-full.png)
    profile_image_filename = f"{target['id']}.png"
    dst_dir = community.get_profile_images_dir()
    dst = os.path.join(dst_dir, profile_image_filename)
    shutil.copy2(sample_path, dst)

    # -full 변형도 같이 복사 (lightbox 용)
    base, ext = os.path.splitext(sample_file)
    sample_full_path = os.path.join(sample_dir, f"{base}-full{ext}")
    if os.path.exists(sample_full_path):
        dst_full = os.path.join(dst_dir, f"{target['id']}-full.png")
        shutil.copy2(sample_full_path, dst_full)

    # DB에 profile_image_filename + sample_source_file 업데이트.
    # sample_source_file 은 Creator catalog 에서 중복 추천 방지용 (agent_id.png 는 새 파일명이라 추적 불가).
    conn = db.get_conn()
    conn.execute(
        "UPDATE agents SET profile_image_filename=?, sample_source_file=? WHERE id=?",
        (profile_image_filename, sample_file, target["id"]),
    )
    conn.commit()
    conn.close()

    log_writer.system(f"✓ 샘플 프로필 이미지 적용: {agent_name} ← {sample_file}")

    # Discord webhook avatar 즉시 갱신 — 안 하면 봇 startup 까지 옛/빈 avatar 그대로 사용.
    # 회귀: 사용자가 '하나야 아스나 이미지 적용해줘' 후 dm-아스나 발화 시 webhook avatar 가
    # bot 첫 startup 때의 상태 (= 없음) 로 남아있어 이미지 미반영. 웹 대시보드는 DB·파일 직접
    # 읽어서 정상 표시되지만 디코는 cached webhook 으로 안 보임.
    try:
        from src.bot.core import update_agent_webhook_profile_image
        if guild:
            updated_chs = 0
            for ch in guild.text_channels:
                try:
                    whs = await ch.webhooks()
                    if any(wh.name == f"glimi-{target['id']}" for wh in whs):
                        if await update_agent_webhook_profile_image(ch, target["id"]):
                            updated_chs += 1
                except Exception:
                    pass
            log_writer.system(f"  Webhook avatar 즉시 갱신: {updated_chs}개 채널")
    except Exception as e:
        log_writer.system(f"  Webhook avatar 갱신 실패 (무시): {e}")

    # 확인 메시지는 tool을 호출한 에이전트 (일반적으로 하나=creator)로 보낸다.
    sender_id = caller_agent_id or ("agent-creator-001" if target["type"] == "persona" else target["id"])
    await send_as_agent(report_channel, sender_id, f"{agent_name} 프로필 이미지 적용했어!")


# ── ACTION 전달 ──────────────────────────────────────────


async def _forward_action_to_yuna(agent_id: str, action_str: str, guild):
    """페르소나의 ACTION 요청을 유나에게 전달 → 유나가 승인/거절
    유나 자신의 ACTION은 직접 CMD로 변환 실행"""
    if not guild:
        return

    # ACTION 파싱 (JSON 또는 레거시)
    action_str = action_str.strip()
    if action_str.startswith("{"):
        try:
            import json as _json
            data = _json.loads(action_str)
            action_type = data.get("type", data.get("action", "")).upper()
            target_name = _resolve_agent_name(data.get("target", data.get("name", "")))
            message = data.get("message", data.get("msg", ""))
            action_args = f"{target_name} {message}".strip() if target_name else message
        except (ValueError, KeyError):
            parts = action_str.split(None, 1)
            action_type = parts[0].upper() if parts else ""
            action_args = parts[1] if len(parts) > 1 else ""
    else:
        parts = action_str.split(None, 1)
        action_type = parts[0].upper() if parts else ""
        action_args = parts[1] if len(parts) > 1 else ""
        # 레거시에서도 이름 해석
        if action_type == "DM" and action_args:
            dm_parts = action_args.split(None, 1)
            dm_parts[0] = _resolve_agent_name(dm_parts[0])
            action_args = " ".join(dm_parts)

    # DM ACTION 은 caller type 무관 — 모두 동일 경로로 internal-dm-{sender}-{target} 에 직접 투입.
    # (과거엔 persona 의 DM 만 유나 approval flow 로 거쳐서 승인 대기 중 묻히는 UX 버그.)
    if action_type == "DM":
        dm_parts = action_args.split(None, 1)
        target_name = dm_parts[0] if dm_parts else ""
        message = dm_parts[1] if len(dm_parts) > 1 else ""
        if not target_name or not message:
            return
        target = None
        for a in db.list_agents():
            if a["name"] == target_name:
                target = a
                break
        if not target:
            log_writer.system(f"[not_found] DM target agent={target_name}")
            return
        sender_name = runtime.get_agent_name(agent_id)
        from src.bot import internal_dm_channel_name
        ch_name = internal_dm_channel_name(sender_name, target_name)
        alt_ch_name = f"internal-dm-{target_name}-{sender_name}"  # 구 order 호환
        alt_ch_name2 = f"internal-dm-{sender_name}-{target_name}"
        target_ch = (discord.utils.get(guild.text_channels, name=ch_name)
                     or discord.utils.get(guild.text_channels, name=alt_ch_name)
                     or discord.utils.get(guild.text_channels, name=alt_ch_name2))
        if not target_ch:
            from src.bot.core import _get_category_for_channel, _ensure_category
            from src.core.sync import ensure_unique_channel
            cat = await _ensure_category(guild, _get_category_for_channel(ch_name))
            target_ch, _ = await ensure_unique_channel(guild, ch_name, cat)
            db.set_channel_participants(ch_name, [agent_id, target["id"]])
        actual_ch_name = target_ch.name
        await send_as_agent(target_ch, agent_id, message)
        db.log_message(actual_ch_name, agent_id, message)
        log_writer.system(f"✓ {sender_name} → {target_name} DM (#{actual_ch_name})")

        async def _send_fn(aid, msg):
            await send_as_agent(target_ch, aid, msg)

        asyncio.create_task(
            start_conversation(
                actual_ch_name,
                [agent_id, target["id"]],
                _send_fn,
                context=message,
            )
        )
        return

    # 그 외 ACTION — 시스템 에이전트는 직접 실행 경로 (구 로직 유지)
    agent_info = db.get_agent(agent_id)
    is_system_agent = agent_info and agent_info.get("type") in ("mgr", "creator")
    if is_system_agent:
        sender_name = runtime.get_agent_name(agent_id)
        log_writer.system(f"{sender_name} ACTION 직접 실행: {action_type} {action_args[:50]}")
        return

    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    if not mgr_ch:
        return

    agent_name = runtime.get_agent_name(agent_id)
    log_writer.system(f"🔔 ACTION 요청: {agent_name} → {action_str[:80]}")
    asyncio.create_task(send_system_log(f"🔔 ACTION: {agent_name} → {action_str[:60]}"))

    # ACTION 파싱: "DM 이름 메시지" / "톡방 이름1 이름2 첫메시지" / "대화 이름 상황"
    parts = action_str.split(None, 1)
    action_type = parts[0].upper() if parts else ""
    action_args = parts[1] if len(parts) > 1 else ""

    from src.core.profile import get_owner_call_name as _get_oc
    from src.core.prompts.en.mgr_notifications import (
        action_notify_dm_prompt,
        action_notify_room_prompt,
        action_notify_generic_prompt,
    )
    oc = _get_oc() or "오너"

    if action_type == "DM":
        dm_parts = action_args.split(None, 1)
        target_name = dm_parts[0] if dm_parts else ""
        dm_message = dm_parts[1] if len(dm_parts) > 1 else ""
        notify_prompt = action_notify_dm_prompt(
            agent_name=agent_name, agent_id=agent_id,
            target_name=target_name, dm_message=dm_message, oc=oc,
        )
    elif action_type == "톡방":
        if "|" in action_args:
            room_info, first_msg = action_args.split("|", 1)
            room_info = room_info.strip()
            first_msg = first_msg.strip()
        else:
            room_info = action_args
            first_msg = ""
        notify_prompt = action_notify_room_prompt(
            agent_name=agent_name, agent_id=agent_id,
            room_info=room_info, first_msg=first_msg, oc=oc,
        )
    else:
        notify_prompt = action_notify_generic_prompt(
            agent_name=agent_name, action_str=action_str, oc=oc,
        )

    try:
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(
                MGR_ID, MGR_CHANNEL, notify_prompt, log_user_message=False
            )
        )
        if responses:
            responses = await parse_and_execute_actions(mgr_ch, responses, guild)
        for resp in responses:
            for part in _split_for_chat(resp):
                await send_as_agent(mgr_ch, MGR_ID, part)
                await asyncio.sleep(0.3 + random.uniform(0, 0.4))
    except Exception as e:
        log.error(f"[ACTION] 유나 전달 실패: {e}")
