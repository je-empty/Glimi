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

import discord

import src.bot as _bot_state
from src import db
from src import log_writer
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
    CMD_PATTERN, QUERY_PATTERN, ACTION_PATTERN, MAX_QUERY_DEPTH,
    CHANNEL_AGENT_MAP, AGENT_CHANNEL_MAP, GROUP_PARTICIPANTS,
    _webhook_cache, DEV_DIR, DEV_PENDING, DEV_RESULT,
    DAILY_SOCIAL_LIMIT,
)
from src.bot.core import (
    send_as_agent, send_system_log, get_agent_webhook,
    _split_for_chat, _get_plain_webhook,
)


# ── CMD/QUERY 파싱 + 실행 ──────────────────────────────


async def parse_and_execute_actions(
    report_channel: discord.TextChannel,
    responses: list[str],
    guild: discord.Guild,
) -> list[str]:
    """
    유나 응답에서 [CMD:...] / [QUERY:...] 태그를 파싱하고 실행.
    CMD: 즉시 실행 (톡방 생성 등)
    QUERY: DB 조회 → 결과를 유나에게 다시 전달 → 분석 응답만 반환 (원문 버림)
    """
    cleaned = []
    query_results = []
    has_query = False

    for resp in responses:
        cmds = CMD_PATTERN.findall(resp)
        queries = QUERY_PATTERN.findall(resp)
        actions = ACTION_PATTERN.findall(resp)
        clean_text = CMD_PATTERN.sub('', resp)
        clean_text = QUERY_PATTERN.sub('', clean_text)
        clean_text = ACTION_PATTERN.sub('', clean_text).strip()

        if queries:
            has_query = True

        # QUERY 없는 메시지만 cleaned에 추가 (QUERY 있으면 followup이 대체)
        if clean_text and not queries:
            cleaned.append(clean_text)

        # CMD 실행
        for cmd_str in cmds:
            try:
                await execute_yuna_command(report_channel, cmd_str.strip(), guild)
            except Exception as e:
                log.error(f"[유나CMD] 실행 실패: {cmd_str} → {e}")
                await send_as_agent(report_channel, MGR_ID, f"명령 실행 실패했어.. ({str(e)[:60]})")

        # ACTION 처리 (유나 → 직접 실행, 페르소나 → 유나에게 전달)
        for action in actions:
            try:
                await _forward_action_to_yuna(MGR_ID, action.strip(), guild)
            except Exception as e:
                log.error(f"[ACTION] 실행 실패: {action} → {e}")

        # QUERY 수집
        for q_str in queries:
            result = await execute_yuna_query(q_str.strip(), guild)
            if result:
                query_results.append(result)

    # QUERY 결과가 있으면 유나에게 다시 전달해서 분석 받기
    if query_results:
        followup = await _yuna_followup_with_data(
            report_channel, "\n\n".join(query_results), guild
        )
        if followup:
            cleaned.extend(followup)

    return cleaned


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


async def _yuna_followup_with_data(
    report_channel: discord.TextChannel,
    data_text: str,
    guild: discord.Guild,
    depth: int = 0,
) -> list[str]:
    """조회 결과를 유나에게 전달 → 분석 응답 받기 (재귀 가능)"""
    if depth >= MAX_QUERY_DEPTH:
        log.warning("[유나QUERY] 최대 깊이 도달")
        return []

    followup_prompt = (
        f"아래는 네가 요청한 조회 결과야. 분석해서 보고해.\n\n"
        f"{data_text}\n\n"
        f"추가 조회가 필요하면 [QUERY:...] 태그를 다시 써도 돼."
    )

    loop = asyncio.get_event_loop()
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response(
            MGR_ID, "mgr-dashboard", followup_prompt, log_user_message=False
        )
    )

    # 재귀: 후속 응답에도 CMD/QUERY가 있을 수 있음
    cleaned = []
    more_queries = []

    for resp in responses:
        # CMD 실행
        cmds = CMD_PATTERN.findall(resp)
        for cmd_str in cmds:
            try:
                await execute_yuna_command(report_channel, cmd_str.strip(), guild)
            except Exception as e:
                log.error(f"[유나CMD] followup 실행 실패: {cmd_str} → {e}")

        # QUERY 수집
        queries = QUERY_PATTERN.findall(resp)
        for q_str in queries:
            result = await execute_yuna_query(q_str.strip(), guild)
            if result:
                more_queries.append(result)

        # 태그 제거된 텍스트
        clean_text = CMD_PATTERN.sub('', resp)
        clean_text = QUERY_PATTERN.sub('', clean_text).strip()
        if clean_text:
            cleaned.append(clean_text)

    # 추가 쿼리가 있으면 재귀
    if more_queries:
        deeper = await _yuna_followup_with_data(
            report_channel, "\n\n".join(more_queries), guild, depth + 1
        )
        if deeper:
            cleaned.extend(deeper)

    return cleaned


# ── CMD 실행 ─────────────────────────────────────────────


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


def _parse_cmd_json(cmd_str: str) -> tuple[str, str]:
    """CMD 문자열 파싱 — JSON 또는 레거시 스페이스 구분 모두 지원.
    Returns: (cmd, args_str) — 기존 execute_yuna_command 호환 형식
    """
    cmd_str = cmd_str.strip()

    # JSON 형식 시도
    if cmd_str.startswith("{"):
        try:
            import json as _json
            data = _json.loads(cmd_str)
            cmd = data.get("cmd", data.get("type", ""))

            # 이름 필드들 해석
            for key in ("name", "target", "이름"):
                if key in data and isinstance(data[key], str):
                    data[key] = _resolve_agent_name(data[key])
            if "names" in data and isinstance(data["names"], list):
                data["names"] = [_resolve_agent_name(n) for n in data["names"]]

            # cmd별 args_str 생성 (기존 형식 호환)
            if cmd == "톡방":
                names = " ".join(data.get("names", []))
                topic = data.get("topic", "")
                return cmd, f"{names} {topic}".strip()
            elif cmd == "대화시작":
                names = " ".join(data.get("names", []))
                situation = data.get("situation", data.get("context", ""))
                return cmd, f"{names} {situation}".strip()
            elif cmd == "감정":
                return cmd, f"{data.get('name', '')} {data.get('emotion', '')} {data.get('intensity', 5)}"
            elif cmd == "프로필수정":
                return cmd, f"{data.get('name', '')} {data.get('field', '')} {data.get('value', '')}"
            elif cmd == "관계수정":
                return cmd, f"{data.get('name_a', '')} {data.get('name_b', '')} {data.get('field', '')} {data.get('value', '')}"
            elif cmd == "프로필생성":
                return cmd, _json.dumps(data.get("profile", data), ensure_ascii=False)
            else:
                # 기타 — args를 스페이스로 join
                args = data.get("args", data.get("target", data.get("name", "")))
                if isinstance(args, list):
                    return cmd, " ".join(str(a) for a in args)
                return cmd, str(args)
        except (ValueError, KeyError):
            pass  # JSON 파싱 실패 → 레거시 폴백

    # 레거시 스페이스 구분
    parts = cmd_str.split(None, 1)
    cmd = parts[0]
    args_str = parts[1] if len(parts) > 1 else ""

    # 레거시에서도 이름 해석 (첫 번째 인자가 이름인 CMD들)
    name_cmds = {"감정", "프로필수정", "채널삭제", "채널초기화", "에이전트초기화", "오너초대", "강제"}
    if cmd in name_cmds and args_str:
        name_parts = args_str.split(None, 1)
        resolved = _resolve_agent_name(name_parts[0])
        args_str = f"{resolved} {name_parts[1]}" if len(name_parts) > 1 else resolved

    return cmd, args_str


async def execute_yuna_command(
    report_channel: discord.TextChannel,
    cmd_str: str,
    guild: discord.Guild,
):
    """유나의 CMD 태그 하나를 실행"""
    cmd, args_str = _parse_cmd_json(cmd_str)

    log.info(f"[유나CMD] 실행: {cmd} {args_str}")

    # ── 톡방/대화 관리 ──
    if cmd == "톡방":
        await yuna_create_room(report_channel, args_str, guild)
    elif cmd == "대화시작":
        await yuna_start_conversation(report_channel, args_str, guild)
    elif cmd == "오너초대":
        await yuna_invite_owner(report_channel, args_str, guild)
    elif cmd == "감정":
        await yuna_change_emotion(report_channel, args_str)
    elif cmd == "대화중단":
        ch_name = args_str.strip()
        if ch_name == "전체":
            active = list_active_conversations()
            count = 0
            for conv in active:
                stop_conversation(conv["channel"])
                count += 1
            await send_as_agent(report_channel, MGR_ID, f"전체 대화 {count}건 중단했어")
        elif stop_conversation(ch_name):
            await send_as_agent(report_channel, MGR_ID, f"#{ch_name} 대화 중단했어")
        else:
            await send_as_agent(report_channel, MGR_ID, f"#{ch_name}에 진행 중인 대화 없어")

    # ── 디스코드 채널 관리 ──
    elif cmd == "채널삭제":
        await yuna_delete_channel(report_channel, args_str, guild)
    elif cmd == "채널이름변경":
        await yuna_rename_channel(report_channel, args_str, guild)
    elif cmd == "채널토픽":
        await yuna_set_channel_topic(report_channel, args_str, guild)

    # ── 프로필/관계 관리 ──
    elif cmd == "프로필수정":
        await yuna_edit_profile(report_channel, args_str)
    elif cmd == "관계수정":
        await yuna_edit_relationship(report_channel, args_str)

    # ── DB 정리 ──
    elif cmd == "채널초기화":
        await yuna_wipe_channel(report_channel, args_str, guild)
    elif cmd == "대화삭제":
        await yuna_delete_messages(report_channel, args_str)
    elif cmd == "에이전트초기화":
        await yuna_wipe_agent(report_channel, args_str)

    # ── 디스코드 메시지 관리 ──
    elif cmd == "메시지청소":
        await yuna_purge_messages(report_channel, args_str, guild)

    # ── 디코 복구 ──
    elif cmd == "디코복구":
        await yuna_restore_discord(report_channel, args_str, guild)

    # ── 샘플 아바타 적용 ──
    elif cmd == "아바타적용":
        await _apply_sample_avatar(report_channel, args_str, guild)

    # ── ACTION 승인 ──
    elif cmd == "ACTION승인":
        await yuna_approve_action(report_channel, args_str, guild)

    # ── 강제 지시 (유나가 에이전트에게) ──
    elif cmd == "강제":
        await yuna_force_agent(report_channel, args_str, guild)

    # ── 개발 요청 ──
    elif cmd == "개발요청":
        await yuna_dev_request(report_channel, args_str, "유나")

    # ── 프로필 파일 관리 (하나 전용) ──
    elif cmd == "프로필생성":
        await _cmd_profile_create(report_channel, args_str)
    elif cmd == "프로필삭제":
        await _cmd_profile_delete(report_channel, args_str)
    elif cmd == "멤버목록":
        pass  # QUERY로 처리됨

    else:
        log.warning(f"[유나CMD] 알 수 없는 명령: {cmd}")


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
        dm_name = f"dm-{participants[0]['name']}"
        dm_ch = discord.utils.get(guild.text_channels, name=dm_name)
        if not dm_ch:
            category = discord.utils.get(guild.categories, name="glimi")
            dm_ch = await guild.create_text_channel(dm_name, category=category or guild.text_channels[0].category)
            CHANNEL_AGENT_MAP[dm_name] = participants[0]["id"]
            AGENT_CHANNEL_MAP[participants[0]["id"]] = dm_name
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
        await send_as_agent(report_channel, MGR_ID, f"이미 있어: #{ch_name}")
        return

    category = discord.utils.get(guild.categories, name="glimi")
    new_ch = await guild.create_text_channel(
        ch_name, category=category or guild.text_channels[0].category
    )

    # 참여자 등록
    participant_ids = [p["id"] for p in participants]
    GROUP_PARTICIPANTS[ch_name] = participant_ids

    await send_as_agent(report_channel, MGR_ID, f"톡방 만들었어: #{ch_name}")
    log.info(f"[유나CMD] 톡방 생성: {ch_name}")

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

    category = discord.utils.get(guild.categories, name="glimi")
    # 기존 채널 검색 (이름 순서 반대도 체크)
    target_ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not target_ch and len(names) == 2:
        alt = f"{prefix}-{names[1]}-{names[0]}"
        target_ch = discord.utils.get(guild.text_channels, name=alt)
        if target_ch:
            ch_name = alt
    if not target_ch:
        target_ch = await guild.create_text_channel(
            ch_name, category=category or guild.text_channels[0].category
        )

    # 참여자 등록 (기존 채널이든 새 채널이든)
    GROUP_PARTICIPANTS[ch_name] = participant_ids

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
        report_prompt = (
            f"{', '.join(names)} 대화 끝났어 (#{ch_name}, {state.turn_count}턴).\n"
            f"마지막 대화:\n{preview}\n\n"
            f"오빠한테 간략하게 보고해.\n"
            f"대화 내용에서 누군가가 오빠한테 연락하겠다고 했거나 다른 사람한테 연락하려는 상황이면 "
            f"[CMD:대화시작 ...]으로 이어지게 해줘.\n"
            f"[CMD:강제]는 쓰지 마. 네가 직접 강제 지시하면 안 돼."
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
        await send_as_agent(report_channel, MGR_ID, f"채널 못 찾겠어: {ch_name}")
        return

    # mgr-dashboard에 오너한테 알림
    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    notify_ch = mgr_ch or report_channel

    await send_as_agent(notify_ch, MGR_ID,
        f"오빠, #{ch_name} 에서 얘기 중이야. 와서 같이 얘기해!")

    # 해당 채널에도 안내
    await send_as_agent(target_ch, MGR_ID, "오빠 부를게~")
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
        await send_as_agent(report_channel, MGR_ID, f"채널 못 찾겠어: {ch_name}")
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
        await send_as_agent(report_channel, MGR_ID, "형식: [CMD:채널이름변경 기존이름 새이름]")
        return

    old_name, new_name = parts[0], parts[1]
    target_ch = discord.utils.get(guild.text_channels, name=old_name)
    if not target_ch:
        await send_as_agent(report_channel, MGR_ID, f"채널 못 찾겠어: {old_name}")
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
        await send_as_agent(report_channel, MGR_ID, "형식: [CMD:채널토픽 채널명 토픽내용]")
        return

    ch_name, topic = parts[0], parts[1]
    target_ch = discord.utils.get(guild.text_channels, name=ch_name)
    if not target_ch:
        await send_as_agent(report_channel, MGR_ID, f"채널 못 찾겠어: {ch_name}")
        return

    await target_ch.edit(topic=topic)
    await send_as_agent(report_channel, MGR_ID, f"#{ch_name} 토픽 설정 완료")
    log.info(f"[유나CMD] 채널 토픽: {ch_name} → {topic}")


# ── 프로필/관계 관리 ─────────────────────────────────────


async def yuna_edit_profile(report_channel, args_str):
    """유나가 에이전트 프로필 수정 — '이름 필드경로 값'
    예: 최서연 personality.traits.0 소심한
    예: 은하윤 daily_life.routine 학교→도서관→집
    """
    parts = args_str.split(None, 2)
    if len(parts) < 3:
        await send_as_agent(report_channel, MGR_ID, "형식: [CMD:프로필수정 이름 필드경로 값]")
        return

    agent_name, field_path, value = parts[0], parts[1], parts[2]

    # 에이전트에서 먼저 검색
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if target:
        profile = load_profile(target["id"])
        if not profile:
            await send_as_agent(report_channel, MGR_ID, f"{agent_name} 프로필 로드 실패")
            return
    else:
        # 유저(오너)에서 검색
        conn = db.get_conn()
        user = conn.execute("SELECT * FROM users WHERE name LIKE ?", (f"%{agent_name}%",)).fetchone()
        conn.close()
        if user:
            await _edit_user_profile(report_channel, dict(user), field_path, value)
            return
        await send_as_agent(report_channel, MGR_ID, f"{agent_name} 찾을 수 없어")
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
        await send_as_agent(report_channel, MGR_ID,
            f"프로필 수정 실패: {field_path} 경로가 잘못됐어 ({str(e)[:40]})")


async def _edit_user_profile(report_channel, user: dict, field_path: str, value: str):
    """유저(오너) 프로필 필드 수정"""
    import json as _json
    user_id = user["id"]
    user_name = user.get("name", "?")

    # 단순 필드 (users 테이블 직접 컬럼)
    simple_fields = {"name", "age", "birth_year", "mbti", "enneagram", "background"}
    # JSON blob 필드
    json_fields = {"personality", "appearance", "daily_life", "speech"}

    if field_path in simple_fields:
        conn = db.get_conn()
        conn.execute(f"UPDATE users SET {field_path} = ? WHERE id = ?", (value, user_id))
        conn.commit()
        conn.close()
        await send_as_agent(report_channel, MGR_ID, f"{user_name} 프로필 수정: {field_path} → {value}")
        return

    # JSON 필드 (예: personality.gender, speech.style)
    parts = field_path.split(".", 1)
    if parts[0] in json_fields and len(parts) == 2:
        conn = db.get_conn()
        raw = conn.execute(f"SELECT {parts[0]} FROM users WHERE id = ?", (user_id,)).fetchone()
        blob = {}
        if raw and raw[0]:
            try:
                blob = _json.loads(raw[0]) if isinstance(raw[0], str) else raw[0]
            except Exception:
                blob = {}
        blob[parts[1]] = value
        conn.execute(f"UPDATE users SET {parts[0]} = ? WHERE id = ?", (_json.dumps(blob, ensure_ascii=False), user_id))
        conn.commit()
        conn.close()
        await send_as_agent(report_channel, MGR_ID, f"{user_name} 프로필 수정: {field_path} → {value}")
        return

    await send_as_agent(report_channel, MGR_ID, f"유저 프로필 필드 '{field_path}'를 찾을 수 없어")


async def yuna_edit_relationship(report_channel, args_str):
    """유나가 관계 수정 — '이름A 이름B 필드 값'
    예: 은하윤 최지수 intimacy +10
    예: 은하윤 최지수 type 절친
    """
    parts = args_str.split()
    if len(parts) < 4:
        await send_as_agent(report_channel, MGR_ID, "형식: [CMD:관계수정 이름A 이름B 필드 값]")
        return

    name_a, name_b, field, value = parts[0], parts[1], parts[2], " ".join(parts[3:])

    agents = db.list_agents()
    agent_by_name = {a["name"]: a for a in agents}
    agent_by_name[get_user_name()] = {"id": get_user_id(), "name": get_user_name()}

    a = agent_by_name.get(name_a)
    b = agent_by_name.get(name_b)
    if not a or not b:
        await send_as_agent(report_channel, MGR_ID, f"에이전트를 찾을 수 없어: {name_a}, {name_b}")
        return

    if field == "intimacy":
        # +10, -5 같은 상대값 또는 절대값
        if value.startswith("+") or value.startswith("-"):
            delta = int(value)
            db.update_intimacy(a["id"], b["id"], delta)
            await send_as_agent(report_channel, MGR_ID,
                f"{name_a}↔{name_b} 친밀도 {value} 변경")
        else:
            # 절대값 설정
            score = int(value)
            conn = db.get_conn()
            conn.execute(
                "UPDATE relationships SET intimacy_score = ?, updated_at = ? WHERE agent_a = ? AND agent_b = ?",
                (max(0, min(100, score)), datetime.now().isoformat(), a["id"], b["id"])
            )
            conn.commit()
            conn.close()
            await send_as_agent(report_channel, MGR_ID,
                f"{name_a}↔{name_b} 친밀도 → {score}")

    elif field == "type":
        conn = db.get_conn()
        conn.execute(
            "UPDATE relationships SET type = ?, updated_at = ? WHERE agent_a = ? AND agent_b = ?",
            (value, datetime.now().isoformat(), a["id"], b["id"])
        )
        conn.commit()
        conn.close()
        await send_as_agent(report_channel, MGR_ID,
            f"{name_a}↔{name_b} 관계 → {value}")

    elif field == "dynamics":
        conn = db.get_conn()
        conn.execute(
            "UPDATE relationships SET dynamics = ?, updated_at = ? WHERE agent_a = ? AND agent_b = ?",
            (value, datetime.now().isoformat(), a["id"], b["id"])
        )
        conn.commit()
        conn.close()
        await send_as_agent(report_channel, MGR_ID,
            f"{name_a}↔{name_b} 역학 → {value}")

    else:
        await send_as_agent(report_channel, MGR_ID,
            f"관계 필드 '{field}' 모름. 사용 가능: intimacy, type, dynamics")

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
        await send_as_agent(report_channel, MGR_ID, "형식: [CMD:대화삭제 채널 채널명] 또는 [CMD:대화삭제 키워드 검색어]")
        return

    mode = parts[0]

    if mode == "채널":
        ch_name = parts[1]
        result = db.delete_channel_data(ch_name)
        await send_as_agent(report_channel, MGR_ID,
            f"#{ch_name} 대화 {result['messages_deleted']}건 + 메모리 {result['memories_deleted']}건 삭제")

    elif mode == "화자":
        if len(parts) < 3:
            await send_as_agent(report_channel, MGR_ID, "형식: [CMD:대화삭제 화자 채널명 이름]")
            return
        ch_name, agent_name = parts[1], parts[2]
        agents = db.list_agents()
        target = next((a for a in agents if a["name"] == agent_name), None)
        speaker_id = target["id"] if target else (get_user_id() if agent_name == get_user_name() else None)
        if not speaker_id:
            await send_as_agent(report_channel, MGR_ID, f"{agent_name} 못 찾겠어")
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
        await send_as_agent(report_channel, MGR_ID, f"{agent_name} 못 찾겠어")
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
        await send_as_agent(report_channel, MGR_ID, f"채널 못 찾겠어: {ch_name}")
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
        await send_as_agent(report_channel, MGR_ID, f"채널 못 찾겠어: {ch_name}")
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
        text = msg["message"]

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
            await send_as_agent(report_channel, MGR_ID, "DM 형식: ACTION승인 DM ID 이름 메시지")
            return
        target_name, message = dm_parts

        target = agent_by_name.get(target_name)
        if not target:
            await send_as_agent(report_channel, MGR_ID, f"{target_name} 못 찾겠어")
            return
        target_id = target["id"]

        # internal-dm 채널 찾기/생성
        ch_name = f"internal-dm-{sender_name}-{target_name}"
        ch_name_alt = f"internal-dm-{target_name}-{sender_name}"
        target_ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_ch:
            target_ch = discord.utils.get(guild.text_channels, name=ch_name_alt)
        if not target_ch:
            category = discord.utils.get(guild.categories, name="internal") or \
                       (guild.categories[0] if guild.categories else None)
            target_ch = await guild.create_text_channel(ch_name, category=category)

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

        # 채널 찾기/생성
        target_ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_ch:
            category = discord.utils.get(guild.categories, name="group") or \
                       (guild.categories[0] if guild.categories else None)
            target_ch = await guild.create_text_channel(ch_name, category=category)

        GROUP_PARTICIPANTS[ch_name] = part_ids

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
        await send_as_agent(report_channel, MGR_ID, f"{agent_name} 못 찾겠어")
        return

    agent_id = target["id"]

    # 채널 존재 확인
    if guild:
        target_ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_ch:
            await send_as_agent(report_channel, MGR_ID, f"채널 못 찾겠어: {ch_name}")
            return

    log_writer.system(f"🔧 유나 강제지시: {agent_name} @ {ch_name} → {instruction[:50]}")

    # generate_response_force 사용 — 유나 존재 노출 없이 시스템 레벨 강제
    loop = asyncio.get_event_loop()
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response_force(agent_id, ch_name, instruction)
    )

    # 해당 채널에 에이전트 응답 전송 (ACTION 태그 처리 포함)
    if guild:
        for resp in responses:
            if ACTION_PATTERN.search(resp):
                actions = ACTION_PATTERN.findall(resp)
                clean_text = ACTION_PATTERN.sub('', resp).strip()
                if clean_text:
                    await send_as_agent(target_ch, agent_id, clean_text)
                for action in actions:
                    await _forward_action_to_yuna(agent_id, action.strip(), guild)
            else:
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
            "timestamp": datetime.now().isoformat(),
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

    if not bot.guilds:
        return
    guild = bot.guilds[0]
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
        dev_report = (
            f"[개발 결과 도착]\n"
            f"상태: {status}\n"
            f"요청자: {requested_by}\n"
            f"결과:\n{message[:2000]}\n\n"
            f"위 개발 결과를 보고 판단해:\n"
            f"1. 성공이면 오빠한테 뭘 고쳤는지 간결하게 보고해\n"
            f"2. 실패했거나 의도대로 안 됐으면 네가 다시 [CMD:개발요청 ...]으로 재요청해 (원래 요청 + 실패 원인 포함)\n"
            f"3. 네 선에서 판단 불가능한 문제면 오빠한테 상황 설명하고 어떻게 할지 물어봐"
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

        from src.core.profile import save_profile
        save_profile(profile)

        # DB 등록
        agent_type = profile.get("type", "persona")
        db.register_agent(profile["id"], agent_type, profile["name"])

        # 관계 설정
        if "relationship_to_owner" in profile:
            db.add_relationship(
                get_user_id(), profile["id"],
                profile["relationship_to_owner"]["type"],
                intimacy=50,
                dynamics=profile["relationship_to_owner"].get("dynamics", "")
            )

        runtime.activate_agent(profile["id"])
        runtime.refresh_agent("agent-mgr-001")

        await send_as_agent(report_channel, creator_id, f"프로필 생성 완료: {profile['name']} ({profile['id']})")
        log_writer.system(f"프로필 생성: {profile['name']} ({profile['id']})")

    except Exception as e:
        await send_as_agent(report_channel, creator_id, f"프로필 생성 실패: {str(e)[:80]}")


async def _cmd_profile_delete(report_channel, args_str):
    """프로필 파일 삭제 (하나 전용)"""
    import os as _os
    creator_id = "agent-creator-001"
    agent_name = args_str.strip()
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name or agent_name in a["name"]), None)

    if not target:
        await send_as_agent(report_channel, creator_id, f"{agent_name} 못 찾겠어")
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
        notify_prompt = (
            f"{agent_name}이(가) 톡방/그룹채팅을 원하는 것 같아. "
            f"메시지: \"{message[:60]}\"\n"
            f"필요하면 [CMD:톡방 ...] 으로 만들어줘."
        )

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


async def _apply_sample_avatar(report_channel, args_str, guild):
    """샘플 아바타를 에이전트에 적용"""
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
            sample_file = data.get("sample", "")
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
        await send_as_agent(report_channel, MGR_ID, f"{agent_name} 못 찾겠어")
        return

    # 샘플 파일 확인
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sample_path = os.path.join(project_root, "assets", "sample_avatars", sample_file)
    if not os.path.exists(sample_path):
        await send_as_agent(report_channel, MGR_ID, f"샘플 파일 못 찾겠어: {sample_file}")
        return

    # 커뮤니티 아바타 디렉토리에 복사 (agent_id.png)
    avatar_filename = f"{target['id']}.png"
    dst = os.path.join(community.get_avatars_dir(), avatar_filename)
    shutil.copy2(sample_path, dst)

    # DB에 avatar_filename 업데이트
    conn = db.get_conn()
    conn.execute("UPDATE agents SET avatar_filename=? WHERE id=?", (avatar_filename, target["id"]))
    conn.commit()
    conn.close()

    log_writer.system(f"✓ 샘플 아바타 적용: {agent_name} ← {sample_file}")
    await send_as_agent(report_channel, target["id"] if target["type"] != "persona" else MGR_ID,
                        f"{agent_name} 아바타 적용했어!")


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

    # 시스템 에이전트(Manager/Creator)가 ACTION을 쓴 경우 → 직접 실행
    agent_info = db.get_agent(agent_id)
    is_system_agent = agent_info and agent_info.get("type") in ("mgr", "creator")
    if is_system_agent:
        mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
        if not mgr_ch:
            return

        if action_type == "DM":
            dm_parts = action_args.split(None, 1)
            target_name = dm_parts[0] if dm_parts else ""
            message = dm_parts[1] if len(dm_parts) > 1 else ""
            if target_name and message:
                # 시스템 에이전트는 시스템 에이전트끼리만 DM (persona에게 직접 DM 차단)
                target_agent = None
                for a in db.list_agents():
                    if a["name"] == target_name:
                        target_agent = a
                        break
                if target_agent and target_agent.get("type") == "persona":
                    log_writer.system(f"⚠ {runtime.get_agent_name(agent_id)} → {target_name} DM 차단 (시스템→persona 불가)")
                    await send_as_agent(mgr_ch, agent_id, f"{target_name}한테는 직접 DM 보낼 수 없어")
                    return
                # 대상 에이전트의 internal-dm 채널에서 메시지 전송
                from src.core.profile import load_profile
                target = None
                for a in db.list_agents():
                    if a["name"] == target_name:
                        target = a
                        break
                if target:
                    sender_name = runtime.get_agent_name(agent_id)
                    ch_name = f"internal-dm-{sender_name}-{target_name}"
                    # 역방향 채널도 체크
                    alt_ch_name = f"internal-dm-{target_name}-{sender_name}"
                    target_ch = (discord.utils.get(guild.text_channels, name=ch_name)
                                 or discord.utils.get(guild.text_channels, name=alt_ch_name))
                    if not target_ch:
                        from src.bot.core import _get_category_for_channel, _ensure_category
                        cat = await _ensure_category(guild, _get_category_for_channel(ch_name))
                        target_ch = await guild.create_text_channel(ch_name, category=cat)
                    await send_as_agent(target_ch, agent_id, message)
                    log_writer.system(f"✓ {sender_name} ACTION DM: → {target_name}")
                    await send_as_agent(mgr_ch, agent_id, f"{target_name}한테 DM 보냈어")

                    # 자율 대화 시작 (역질문도 이어감, 턴 제한 적용)
                    actual_ch_name = target_ch.name
                    db.log_message(actual_ch_name, agent_id, message)

                    async def _send_fn(ch_name, aid, msg):
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

    # 공통 판단 지침
    judge_guide = (
        "판단 기준:\n"
        "- 자연스러운 요청이면 승인하고 오빠한테 간략 보고 (예: '서연이가 소율이한테 DM 보내려고 해서 승인했어')\n"
        "- 이상하거나 판단 어려우면 거절하지 말고 오빠한테 먼저 물어봐 (예: '오빠 이거 승인할까?')"
    )

    if action_type == "DM":
        dm_parts = action_args.split(None, 1)
        target_name = dm_parts[0] if dm_parts else ""
        dm_message = dm_parts[1] if len(dm_parts) > 1 else ""
        notify_prompt = (
            f"[ACTION 요청]\n"
            f"{agent_name}이(가) {target_name}한테 DM 보내고 싶대:\n"
            f"  \"{dm_message[:100]}\"\n\n"
            f"승인하면 [CMD:ACTION승인 DM {agent_id} {target_name} {dm_message}] 써.\n"
            f"{judge_guide}"
        )
    elif action_type == "톡방":
        if "|" in action_args:
            room_info, first_msg = action_args.split("|", 1)
            room_info = room_info.strip()
            first_msg = first_msg.strip()
        else:
            room_info = action_args
            first_msg = ""
        notify_prompt = (
            f"[ACTION 요청]\n"
            f"{agent_name}이(가) 톡방 만들고 싶대:\n"
            f"  참여자: {room_info}\n"
            f"  첫 메시지: \"{first_msg[:100]}\"\n\n"
            f"승인하면 [CMD:ACTION승인 톡방 {agent_id} {room_info} | {first_msg}] 써.\n"
            f"{judge_guide}"
        )
    else:
        notify_prompt = (
            f"[ACTION 요청]\n"
            f"{agent_name}이(가) 행동을 요청했어:\n"
            f"  → {action_str}\n\n"
            f"승인하려면 적절한 CMD를 써.\n"
            f"{judge_guide}"
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
