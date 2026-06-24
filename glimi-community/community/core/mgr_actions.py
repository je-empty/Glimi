# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
mgr_actions — discord-free manager(유나/하나/세나) action spine.

The neutral half of the old ``community/bot/mgr_system.py``: ``<tools>`` dispatch
(``parse_and_execute_actions``) + the ``yuna_*`` action implementations, all routed
through a :class:`community.core.channel_adapter.ChannelAdapter` instead of
``discord.TextChannel`` / ``discord.Guild``.

DECOUPLING (CLAUDE.md): **NEVER ``import discord``** here, and never import
``community.bot.*`` at module level (that package does ``import discord``). The web
process imports this module discord-free.

Signature convention (transport-neutral):
    async def yuna_xxx(channel_name: str, args_str: str, ctx) -> ...
``ctx`` is a :class:`glimi.tools.dispatcher.ToolContext` carrying ``channels``
(the adapter), ``caller_agent_id``, ``channel_name``. Sends go through
``ctx.channels.send_as_agent(channel_name, agent_id, text)``; channel lifecycle
through ``ctx.channels.ensure_channel`` / ``find_channel`` / ``delete_channel`` /
``rename_channel`` / ``set_topic``.

The legacy Discord ``bot/mgr_system.py`` keeps its own ``import discord`` versions
for the (Phase-6-doomed) Discord transport; ``bot/mgr_system.py`` re-exports
``parse_and_execute_actions`` / ``_tool_followup_generate`` / ``_sanitize_dm_name``
from here so existing web/dev_queue callers keep working.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

from community import db
from community import log_writer
from community.core.timeutil import now_utc_iso
from community.core.channels import MGR_ID
from community.core.profile import (
    load_profile, get_user_name, get_user_id,
)
from community.core.runtime import runtime


# ── manager-channel name resolution (community-aware, discord-free) ─────────
# The seed default lives in core.channels (MGR_CHANNEL = "dm-서유나"); a community
# may rename the manager. Resolve from the DB agent name when possible.

def _mgr_dm_channel_name() -> str:
    try:
        row = db.get_agent(MGR_ID)
        name = (row or {}).get("name")
        if name:
            from community.core.channels import _norm_name_for_channel
            return f"dm-{_norm_name_for_channel(name)}"
    except Exception:
        pass
    from community.core.channels import MGR_CHANNEL
    return MGR_CHANNEL


# ── DM channel name sanitize (was mgr_system._sanitize_dm_name) ─────────────

def _sanitize_dm_name(agent_name: str) -> str:
    """페르소나 이름 → dm 채널 이름. 공백/특수문자 정규화 (discord-free)."""
    from community.core.channels import _norm_name_for_channel
    if not agent_name:
        return "dm-unknown"
    s = _norm_name_for_channel(agent_name)
    return f"dm-{s}" if s else "dm-unknown"


# ── <tools> dispatch — THE web-critical entrypoint ──────────────────────────

async def parse_and_execute_actions(
    channel_name: str,
    responses: list[str],
    *,
    channels,
    caller_agent_id: Optional[str] = None,
) -> list[str]:
    """신규 Tool Protocol 실행 (transport-neutral).

    - runtime 에 stash 된 tool_calls 를 dispatcher 로 실행 (ctx.channels = 어댑터)
    - query 결과 있으면 followup generate → 분석 응답 추가 반환
    - responses 는 chat 만 (tool 블록은 이미 runtime 이 제거)

    stash→pop 은 호출자가 잡은 active community scope 안에서 일어나야 한다(3.0).
    web 의 _run_turn 은 이미 run_in_community 안에서 이걸 부른다.
    """
    from glimi.tools import run_tools, ToolContext, format_results_block, get_tool

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
        channel_name=channel_name or "",
        channels=channels,
    )
    results = await run_tools(calls, ctx)

    for r in results:
        mark = "✓" if r.ok else "✗"
        tail = str(r.data)[:80] if r.ok and r.data else (r.error or "")
        log_writer.system(f"[Tool] {mark} {r.tool} {tail}")

    has_query_result = any(
        (get_tool(r.tool) and get_tool(r.tool).category == "query") for r in results if r.ok
    )
    if has_query_result:
        block = format_results_block(results)
        runtime.stash_tool_results(agent_id, ctx.channel_name, block)
        followup = await _tool_followup_generate(channel_name, agent_id)
        if followup:
            cleaned.extend(followup)

    return cleaned


async def _tool_followup_generate(channel_name: str, agent_id: str) -> list[str]:
    """tool_results stash 된 상태에서 에이전트 재생성 — 결과 분석 chat 만 반환."""
    loop = asyncio.get_event_loop()
    ch_name = channel_name or ""
    trigger = "(위 tool_results를 보고 자연스럽게 마무리해. 결과를 대화에 녹여서 간결하게. 추가 도구 호출 불필요하면 tools 블록 비워도 돼.)"
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response(
            agent_id, ch_name, trigger, log_user_message=False
        )
    )
    return [r for r in responses if r and r.strip()]


# ── name resolution helper ──────────────────────────────────────────────────

def _resolve_agent_name(name_or_alias: str) -> str:
    """이름, 별칭, ID → 실제 에이전트 이름으로 변환 (DB only, discord-free)."""
    if not name_or_alias:
        return name_or_alias
    name_or_alias = name_or_alias.strip()
    for a in db.list_agents():
        if a["name"] == name_or_alias:
            return a["name"]
    agent = db.get_agent(name_or_alias)
    if agent:
        return agent["name"]
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
    for a in db.list_agents():
        if a["name"].startswith(name_or_alias):
            return a["name"]
    return name_or_alias


# ── query (DB branches only — 디코* branches dropped; no web analog) ─────────

async def execute_yuna_query(query_str: str, *, channels=None) -> str:
    """유나의 QUERY 실행 → 텍스트 결과 (DB only). 디스코드 직접 조회 브랜치는 제거."""
    query_str = (query_str or "").strip()
    if query_str.startswith("{"):
        try:
            data = json.loads(query_str)
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
        cmd = parts[0] if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        if cmd in ("프로필", "관계", "발화", "이벤트") and args:
            args = _resolve_agent_name(args.split()[0]) + (
                " " + " ".join(args.split()[1:]) if len(args.split()) > 1 else ""
            )

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
        limit = min(limit, 100)
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
            lines.append(
                f"- {a['name']} ({a.get('type','?')}) | "
                f"{a.get('age', (profile or {}).get('age', '?'))}살 | {rel} | {a['status']}"
            )
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
        return f"[{agent_name} 프로필]\n{json.dumps(profile, ensure_ascii=False, indent=2)}"

    elif cmd == "관계":
        agent_name = args.strip()
        if not agent_name:
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

    return f"[조회결과] 알 수 없는 쿼리: {cmd}"


# ── room / conversation ─────────────────────────────────────────────────────

async def yuna_create_room(channel_name: str, args_str: str, ctx) -> None:
    """톡방 생성 — 에이전트끼리면 internal, 오너 포함이면 group (adapter-routed)."""
    channels = ctx.channels
    agents_db = db.list_agents()
    agent_names = {a["name"]: a for a in agents_db}

    tokens = args_str.split()
    participants: list[dict] = []
    topic_parts: list[str] = []
    has_owner = False
    for t in tokens:
        if t == get_user_name():
            has_owner = True
        elif t in agent_names:
            participants.append(agent_names[t])
        else:
            matched = next((a for name, a in agent_names.items() if t in name), None)
            if matched:
                participants.append(matched)
            else:
                topic_parts.append(t)

    min_needed = 1 if has_owner else 2
    if len(participants) < min_needed:
        await channels.send_as_agent(channel_name, MGR_ID, "톡방 만들려면 2명 이상 필요해")
        return

    if has_owner and len(participants) == 1:
        dm_name = _sanitize_dm_name(participants[0]["name"])
        existing = await channels.find_channel(dm_name)
        if not existing:
            await channels.ensure_channel(dm_name, participants=[participants[0]["id"]])
            db.set_channel_participants(dm_name, [participants[0]["id"]])
        await channels.send_as_agent(channel_name, MGR_ID, f"dm 채널 준비 완료: #{dm_name}")
        return

    names = [p["name"] for p in participants]
    topic = " ".join(topic_parts) if topic_parts else None

    if has_owner:
        prefix = "group"
    elif len(participants) == 2:
        prefix = "internal-dm"
    else:
        prefix = "internal-group"
    ch_name = f"{prefix}-{'-'.join(names)}"

    existing = await channels.find_channel(ch_name)
    if not existing and len(names) == 2:
        alt = f"{prefix}-{names[1]}-{names[0]}"
        existing = await channels.find_channel(alt)
        if existing:
            ch_name = existing.name

    if existing:
        log_writer.system(f"[create_room] 이미 존재: #{ch_name} (skip)")
        return

    participant_ids = [p["id"] for p in participants]
    await channels.ensure_channel(ch_name, participants=participant_ids)
    db.set_channel_participants(ch_name, participant_ids)

    await channels.send_as_agent(channel_name, MGR_ID, f"톡방 만들었어: #{ch_name}")
    try:
        kind = "단톡방생성" if has_owner else ("비밀톡방생성" if prefix.startswith("internal-") else "톡방생성")
        participant_names = ["owner" if has_owner else None] + [p["name"] for p in participants]
        participant_names = [x for x in participant_names if x]
        db.log_event(kind, participant_names,
                     f"#{ch_name} 생성" + (f" (주제: {topic})" if topic else ""),
                     impact="긍정")
    except Exception:
        pass

    if ch_name.startswith("internal-"):
        async def send_fn(agent_id: str, message: str):
            await channels.send_as_agent(ch_name, agent_id, message)

        context = topic if topic else "자연스럽게 대화 시작"
        asyncio.create_task(_run_and_report_yuna(
            channel_name, ch_name, participant_ids, send_fn, context, channels=channels
        ))


async def yuna_start_conversation(channel_name: str, args_str: str, ctx) -> None:
    """에이전트간 자동 대화 시작 (adapter-routed)."""
    channels = ctx.channels
    agents_db = db.list_agents()
    agent_names = {a["name"]: a for a in agents_db}

    tokens = args_str.split()
    participants: list[dict] = []
    context_parts: list[str] = []
    for t in tokens:
        if t in agent_names:
            participants.append(agent_names[t])
        else:
            matched = next((a for name, a in agent_names.items() if t in name), None)
            if matched and matched not in participants:
                participants.append(matched)
            else:
                context_parts.append(t)

    if len(participants) < 2:
        await channels.send_as_agent(channel_name, MGR_ID, "대화시키려면 2명 이상 필요해")
        return

    names = [p["name"] for p in participants]
    participant_ids = [p["id"] for p in participants]
    context = " ".join(context_parts) if context_parts else ""
    prefix = "internal-dm" if len(participants) == 2 else "internal-group"
    ch_name = f"{prefix}-{'-'.join(names)}"

    existing = await channels.find_channel(ch_name)
    if not existing and len(names) == 2:
        alt = f"{prefix}-{names[1]}-{names[0]}"
        existing = await channels.find_channel(alt)
        if existing:
            ch_name = existing.name
    if not existing:
        await channels.ensure_channel(ch_name, participants=participant_ids)

    db.set_channel_participants(ch_name, participant_ids)

    async def send_fn(agent_id: str, message: str):
        await channels.send_as_agent(ch_name, agent_id, message)

    asyncio.create_task(_run_and_report_yuna(
        channel_name, ch_name, participant_ids, send_fn, context, channels=channels
    ))


async def _run_and_report_yuna(report_channel_name, ch_name, participant_ids,
                               send_fn, context, *, channels) -> None:
    """자동 대화 실행 후 유나가 판단 — 오너에게 알릴 게 있으면 후속 보고 (adapter-routed)."""
    from community.core.conversation_bridge import start_conversation
    try:
        state = await start_conversation(ch_name, participant_ids, send_fn, context=context)
        names = [runtime.get_agent_name(aid) for aid in participant_ids]
        recent = db.get_recent_messages(ch_name, limit=5)
        preview = ""
        if recent:
            preview = "\n".join(
                f"  {runtime.get_agent_name(r['speaker'])}: {r['message'][:50]}"
                for r in recent[-3:]
            )
        from community.core.profile import get_owner_call_name as _get_oc
        from community.core.prompts.en.mgr_notifications import conversation_report_prompt
        oc = _get_oc() or "오너"
        mgr_dm = _mgr_dm_channel_name()
        report_prompt = conversation_report_prompt(
            names=names, channel=ch_name, turn_count=state.turn_count,
            preview=preview, oc=oc,
        )
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(MGR_ID, mgr_dm, report_prompt, log_user_message=False)
        )
        if responses:
            responses = await parse_and_execute_actions(
                report_channel_name or mgr_dm, responses,
                channels=channels, caller_agent_id=MGR_ID,
            )
        for resp in responses:
            await channels.send_as_agent(report_channel_name or mgr_dm, MGR_ID, resp)
    except Exception as e:
        await channels.send_as_agent(report_channel_name or _mgr_dm_channel_name(), MGR_ID,
                                     f"대화 오류: {str(e)[:80]}")


# ── emotion ─────────────────────────────────────────────────────────────────

async def yuna_change_emotion(channel_name: str, args_str: str, ctx) -> None:
    """에이전트 감정 변경 (DB only; channel/ctx 무시 가능)."""
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
    try:
        runtime.refresh_agent(target["id"])
    except Exception:
        pass


# ── channel admin (adapter-routed; DB-backed registry via db.* in adapter) ──

async def yuna_delete_channel(channel_name: str, args_str: str, ctx) -> None:
    target = args_str.strip()
    ok = await ctx.channels.delete_channel(target, reason="mgr delete")
    if not ok:
        log_writer.system(f"[delete_channel] 실패/보호됨: #{target}")


async def yuna_rename_channel(channel_name: str, args_str: str, ctx) -> None:
    parts = args_str.split(None, 1)
    if len(parts) < 2:
        await ctx.channels.send_as_agent(channel_name, MGR_ID, "형식: rename 기존채널 새이름")
        return
    old_name, new_name = parts[0].strip(), parts[1].strip()
    ok = await ctx.channels.rename_channel(old_name, new_name)
    if ok:
        # GROUP_PARTICIPANTS key rename (3-line salvage) — 메모리 캐시 동기화.
        try:
            from community.core import channels as _ch_consts
            gp = getattr(_ch_consts, "GROUP_PARTICIPANTS", None)
            if isinstance(gp, dict) and old_name in gp:
                gp[new_name] = gp.pop(old_name)
        except Exception:
            pass
    else:
        log_writer.system(f"[rename_channel] 실패: #{old_name} → #{new_name}")


async def yuna_set_channel_topic(channel_name: str, args_str: str, ctx) -> None:
    parts = args_str.split(None, 1)
    if len(parts) < 2:
        await ctx.channels.send_as_agent(channel_name, MGR_ID, "형식: topic 채널 주제")
        return
    ch, topic = parts[0].strip(), parts[1].strip()
    ok = await ctx.channels.set_topic(ch, topic)
    if not ok:
        log_writer.system(f"[set_topic] 실패: #{ch}")


async def yuna_wipe_channel(channel_name: str, args_str: str, ctx) -> None:
    """채널 대화 내용 삭제 (메시지 purge — 채널 자체는 유지)."""
    target = args_str.strip()
    n = await ctx.channels.purge_messages(target, 10_000)
    log_writer.system(f"[wipe_channel] #{target} {n}건 삭제")


async def yuna_delete_messages(channel_name: str, args_str: str, ctx) -> None:
    """최근 N건 메시지 삭제."""
    parts = args_str.split()
    ch = parts[0] if parts else channel_name
    try:
        n = int(parts[1]) if len(parts) > 1 else 10
    except ValueError:
        n = 10
    deleted = await ctx.channels.purge_messages(ch, n)
    log_writer.system(f"[delete_messages] #{ch} {deleted}건 삭제")


async def yuna_wipe_agent(channel_name: str, args_str: str, ctx) -> None:
    """에이전트 데이터 초기화 (DB only)."""
    name = args_str.strip()
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == name), None)
    if not target:
        log_writer.system(f"[wipe_agent] not_found: {name}")
        return
    try:
        result = db.delete_agent_all_data(target["id"])
        await ctx.channels.send_as_agent(
            channel_name, MGR_ID,
            f"{name} 데이터 전체 삭제: 대화 {result['messages']}건, "
            f"메모리 {result['memories']}건, 이벤트 {result['events']}건")
    except Exception as e:
        log_writer.system(f"[wipe_agent] 실패: {type(e).__name__}: {e}")


# ── profile edit (DB-pure spine; sends via adapter) ─────────────────────────

_recent_profile_edits: dict[tuple, tuple] = {}
_PROFILE_EDIT_DEDUP_SECONDS = 60.0


async def yuna_edit_profile(channel_name: str, args_str: str, ctx) -> None:
    """에이전트/유저 프로필 수정 — '이름 필드경로 값' (DB only; send via adapter)."""
    channels = ctx.channels
    parts = args_str.split(None, 2)
    if len(parts) < 3:
        await channels.send_as_agent(channel_name, MGR_ID, "update_profile 인자 부족 — name/field/value 필요")
        return
    agent_name, field_path, value = parts[0], parts[1], parts[2]

    import time as _time
    dedup_key = (agent_name, field_path)
    prev = _recent_profile_edits.get(dedup_key)
    now = _time.time()
    if prev and prev[0] == value and (now - prev[1]) < _PROFILE_EDIT_DEDUP_SECONDS:
        log_writer.system(f"[프로필] 중복 수정 스킵: {agent_name}.{field_path} → {value}")
        return
    _recent_profile_edits[dedup_key] = (value, now)

    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if target:
        profile = load_profile(target["id"])
        if not profile:
            log_writer.system(f"[프로필] {agent_name} 프로필 로드 실패")
            return
    else:
        conn = db.get_conn()
        user = conn.execute("SELECT * FROM users WHERE name LIKE ?", (f"%{agent_name}%",)).fetchone()
        conn.close()
        if user:
            await _edit_user_profile(dict(user), field_path, value)
            return
        log_writer.system(f"[프로필] '{agent_name}' 찾을 수 없음")
        return

    keys = field_path.split(".")
    obj = profile
    try:
        for key in keys[:-1]:
            obj = obj[int(key)] if key.isdigit() else obj[key]
        last_key = keys[-1]
        if last_key.isdigit():
            obj[int(last_key)] = value
        else:
            obj[last_key] = value
        from community.core.profile import save_profile
        save_profile(profile)
        runtime.refresh_agent(target["id"])
        await channels.send_as_agent(channel_name, MGR_ID,
            f"{agent_name} 프로필 수정 완료: {field_path} → {value}")
    except (KeyError, IndexError, TypeError) as e:
        log_writer.system(f"[프로필] 수정 실패: {field_path} 경로 오류 ({str(e)[:40]})")


def _values_equivalent(a: str, b: str) -> bool:
    """두 값이 의미상 같은지 — 중복 프로필 수정 필터 (verbatim from mgr_system)."""
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
    if btoks.issubset(atoks):
        return True
    inter = atoks & btoks
    union = atoks | btoks
    return (len(inter) / len(union)) >= 0.6


async def _edit_user_profile(user: dict, field_path: str, value: str) -> None:
    """유저(오너) 프로필 필드 수정 (DB only)."""
    user_id = user["id"]
    user_name = user.get("name", "?")
    simple_fields = {"name", "age", "birth_year", "mbti", "enneagram", "background"}
    json_fields = {"personality", "appearance", "daily_life", "speech"}
    from community.core.profile import invalidate_cache as _invalidate_profile_cache

    def _refresh_active_agents():
        try:
            from community.core.runtime import runtime as _runtime
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
        _invalidate_profile_cache()
        _refresh_active_agents()
        log_writer.system(f"[프로필] {user_name} 수정: {field_path} → {value}")
        return

    parts = field_path.split(".", 1)
    if parts[0] in json_fields:
        conn = db.get_conn()
        if len(parts) == 2:
            raw = conn.execute(f"SELECT {parts[0]} FROM users WHERE id = ?", (user_id,)).fetchone()
            blob = {}
            if raw and raw[0]:
                try:
                    blob = json.loads(raw[0]) if isinstance(raw[0], str) else raw[0]
                except Exception:
                    blob = {}
            if _values_equivalent(blob.get(parts[1]), value):
                conn.close()
                log_writer.system(f"[프로필] {user_name}.{field_path} 이미 '{blob.get(parts[1])}' ≈ '{value}' — 저장 스킵")
                return
            blob[parts[1]] = value
            conn.execute(f"UPDATE users SET {parts[0]} = ? WHERE id = ?",
                         (json.dumps(blob, ensure_ascii=False), user_id))
        else:
            if value.startswith("{"):
                conn.execute(f"UPDATE users SET {field_path} = ? WHERE id = ?", (value, user_id))
            else:
                conn.execute(f"UPDATE users SET {field_path} = ? WHERE id = ?",
                             (json.dumps({"style": value}, ensure_ascii=False), user_id))
        conn.commit()
        conn.close()
        _invalidate_profile_cache()
        _refresh_active_agents()
        log_writer.system(f"[프로필] {user_name} 수정: {field_path} → {value}")
        return


# ── relationship edit — delegate to legacy DB spine (discord-free part) ──────

async def yuna_edit_relationship(channel_name: str, args_str: str, ctx,
                                 caller_agent_id: str = "") -> Any:
    """관계 수정 — '이름A 이름B 필드 값'  (ported from bot/mgr_system.py, discord-free).

    예: 은하윤 최지수 intimacy +10  /  은하윤 최지수 type 절친
    허용 필드: intimacy / affection (intimacy 의 alias) / type / dynamics.
    Self-modification 금지: caller(mgr/creator) 가 자기 자신의 호감도를 직접 올리는 호출 거부
    (LLM placebo-drift 안전망). 실제 호감도는 자연 누적(메모리 추출 +1)으로만.

    report send 는 어댑터(ctx.channels.send_as_agent)로 라우팅.
    """
    channels = ctx.channels
    parts = args_str.split()
    if len(parts) < 4:
        await channels.send_as_agent(channel_name, MGR_ID,
            "update_relationship 인자 부족 — agent_a/agent_b/field/value 필요")
        return {"ok": False, "error": "args 부족"}

    name_a, name_b, field, value = parts[0], parts[1], parts[2], " ".join(parts[3:])

    agents = db.list_agents()
    agent_by_name = {a["name"]: a for a in agents}
    agent_by_name[get_user_name()] = {"id": get_user_id(), "name": get_user_name()}

    a = agent_by_name.get(name_a)
    b = agent_by_name.get(name_b)
    if not a or not b:
        await channels.send_as_agent(channel_name, MGR_ID,
            f"에이전트를 찾을 수 없어: {name_a}, {name_b}")
        return {"ok": False, "error": "agent not found"}

    # ── Self-modification guard ──
    # mgr/creator 가 자기 자신을 한쪽 끝으로 두고 intimacy/affection 을 직접 올리는 호출 거부.
    caller = caller_agent_id or getattr(ctx, "caller_agent_id", "") or ""
    if caller:
        caller_agent = db.get_agent(caller)
        caller_type = (caller_agent or {}).get("type", "")
        if caller_type in ("mgr", "creator"):
            if a["id"] == caller or b["id"] == caller:
                if field in ("intimacy", "affection"):
                    log_writer.system(
                        f"[권한거부] {caller}({caller_type}) 가 자기 자신의 관계 호감도 직접 수정 시도 차단: "
                        f"{name_a}↔{name_b} {field}={value}"
                    )
                    await channels.send_as_agent(channel_name, MGR_ID,
                        "내 호감도/친밀도는 내가 직접 올리거나 내릴 수 없어. "
                        "관계는 자연스러운 대화로만 쌓여."
                    )
                    return {"ok": False, "error": "self_modification_denied",
                            "rule": "mgr/creator cannot edit own affection/intimacy"}

    # ── Field 정규화 + 분기 ──
    field_norm = field.lower()
    if field_norm in ("intimacy", "affection", "호감도", "친밀도"):
        existing = db.get_relationship(a["id"], b["id"]) or db.get_relationship(b["id"], a["id"])
        if not existing:
            db.add_relationship(a["id"], b["id"], rel_type="", intimacy=db.INTIMACY_SCALE_DEFAULT)
            existing = db.get_relationship(a["id"], b["id"])
        if value.startswith("+") or value.startswith("-"):
            delta = int(value)
            db.update_intimacy(a["id"], b["id"], delta)
            await channels.send_as_agent(channel_name, MGR_ID,
                f"{name_a}↔{name_b} 호감도 {value} 변경")
            return {"ok": True, "delta": delta}
        score = max(0, min(100, int(value)))
        conn = db.get_conn()
        for ax, bx in [(a["id"], b["id"]), (b["id"], a["id"])]:
            conn.execute(
                "UPDATE relationships SET intimacy_score=?, updated_at=? WHERE agent_a=? AND agent_b=?",
                (score, now_utc_iso(), ax, bx),
            )
        conn.commit()
        conn.close()
        await channels.send_as_agent(channel_name, MGR_ID,
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
        await channels.send_as_agent(channel_name, MGR_ID,
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
        await channels.send_as_agent(channel_name, MGR_ID,
            f"{name_a}↔{name_b} 역학 → {value}")
        return {"ok": True, "dynamics": value}

    else:
        log_writer.system(
            f"[update_relationship] 알 수 없는 필드 '{field}' (caller={caller}) — DB 변경 0"
        )
        await channels.send_as_agent(channel_name, MGR_ID,
            f"관계 필드 '{field}' 모름. 사용 가능: intimacy(=affection) / type / dynamics")
        return {"ok": False, "error": "unknown_field", "field": field,
                "allowed": ["intimacy", "affection", "type", "dynamics"]}


# ── force agent (commitment supervisor + invoke_agent tool) ─────────────────

async def yuna_force_agent(channel_name: str, args_str: str, ctx) -> None:
    """특정 에이전트에게 강제 지시 — 에이전트는 매니저 존재 모름 (adapter-routed).

    NEW signature (Phase 3.4): (channel_name, args_str, ctx). 호출부(commitment.py,
    tool_handlers._h_invoke) 동일 커밋에서 갱신됨.
    """
    channels = ctx.channels
    parts = args_str.split(None, 2)
    if len(parts) < 3:
        await channels.send_as_agent(channel_name, MGR_ID, "형식: 강제 이름 채널명 지시내용")
        return
    agent_name, ch_name, instruction = parts[0], parts[1], parts[2]

    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)
    if not target:
        log_writer.system(f"[not_found] kind=agent name={agent_name}")
        return
    agent_id = target["id"]

    # 채널 존재 확인 — 공백 정규화 fallback (adapter find_channel)
    found = await channels.find_channel(ch_name)
    if not found:
        from community.core.channels import normalize_channel_name
        normalized = normalize_channel_name(ch_name)
        if normalized != ch_name and await channels.find_channel(normalized):
            log_writer.system(f"[invoke_agent] 채널명 정규화 매칭: '{ch_name}' → '{normalized}'")
            ch_name = normalized
        else:
            log_writer.system(f"[not_found] kind=channel name={ch_name}")
            return

    log_writer.system(f"🔧 강제지시: {agent_name} @ {ch_name} → {instruction[:50]}")

    loop = asyncio.get_event_loop()
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response_force(agent_id, ch_name, instruction)
    )
    if not responses:
        await channels.send_as_agent(channel_name, MGR_ID,
            f"⚠ {agent_name}한테 강제지시 보냈는데 응답 못 받았어 (#{ch_name})")
        return
    for resp in responses:
        await channels.send_as_agent(ch_name, agent_id, resp)
    await channels.send_as_agent(channel_name, MGR_ID,
        f"✓ {agent_name}한테 강제 지시 완료 (#{ch_name})")


# ── dev request (web: queue insert only; no bot.close) ──────────────────────

def create_dev_request(description: str, requested_by: str) -> None:
    """개발 요청 파일 생성 (pending.json). discord-free.

    DEV_DIR 는 active community 의 dev 디렉토리 — bot/__init__ (discord) 를 거치지
    않고 community.get_community_dir() 로 직접 계산.
    """
    from community import community as _comm
    dev_dir = str(_comm.get_community_dir() / "dev")
    pending = os.path.join(dev_dir, "pending.json")
    os.makedirs(dev_dir, exist_ok=True)
    with open(pending, "w", encoding="utf-8") as f:
        json.dump({
            "description": description,
            "requested_by": requested_by,
            "timestamp": now_utc_iso(),
        }, f, ensure_ascii=False, indent=2)
    log_writer.system(f"[Dev] 요청 생성 — {description[:50]}")


# ── persona ACTION forward (DM = internal-dm; adapter-routed) ───────────────

async def forward_action(agent_id: str, action_str: str, *, channels) -> None:
    """페르소나의 ACTION 요청 처리 (transport-neutral).

    DM ACTION → internal-dm-{sender}-{target} 채널에 직접 투입 + start_conversation.
    매니저(mgr/creator) ACTION 은 직접 실행 경로(로그만). 그 외 ACTION 은 매니저 알림
    프롬프트로 generate → mgr DM 채널에 게시.
    """
    from community.core.conversation_bridge import start_conversation
    from community.core.channels import internal_dm_channel_name, _norm_name_for_channel

    action_str = (action_str or "").strip()
    if action_str.startswith("{"):
        try:
            data = json.loads(action_str)
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
        if action_type == "DM" and action_args:
            dm_parts = action_args.split(None, 1)
            dm_parts[0] = _resolve_agent_name(dm_parts[0])
            action_args = " ".join(dm_parts)

    if action_type == "DM":
        dm_parts = action_args.split(None, 1)
        target_name = dm_parts[0] if dm_parts else ""
        message = dm_parts[1] if len(dm_parts) > 1 else ""
        if not target_name or not message:
            return
        target = next((a for a in db.list_agents() if a["name"] == target_name), None)
        if not target:
            log_writer.system(f"[not_found] DM target agent={target_name}")
            return
        sender_name = runtime.get_agent_name(agent_id)
        ch_name = internal_dm_channel_name(sender_name, target_name)
        # 구 order 호환 — 반대 순서 채널이 이미 있으면 그걸 사용
        if not await channels.find_channel(ch_name):
            _ns, _nt = _norm_name_for_channel(sender_name), _norm_name_for_channel(target_name)
            for alt in (f"internal-dm-{_nt}-{_ns}", f"internal-dm-{_ns}-{_nt}"):
                if alt != ch_name and await channels.find_channel(alt):
                    ch_name = alt
                    break
            else:
                await channels.ensure_channel(ch_name, participants=[agent_id, target["id"]])
                db.set_channel_participants(ch_name, [agent_id, target["id"]])
        await channels.send_as_agent(ch_name, agent_id, message)
        log_writer.system(f"✓ {sender_name} → {target_name} DM (#{ch_name})")

        async def _send_fn(aid, msg):
            await channels.send_as_agent(ch_name, aid, msg)

        asyncio.create_task(
            start_conversation(ch_name, [agent_id, target["id"]], _send_fn, context=message)
        )
        return

    # 매니저 직접 실행 경로 (로그만) — 그 외 ACTION 의 알림 generate 는 web 후속.
    agent_info = db.get_agent(agent_id)
    if agent_info and agent_info.get("type") in ("mgr", "creator"):
        log_writer.system(
            f"{runtime.get_agent_name(agent_id)} ACTION 직접 실행: {action_type} {action_args[:50]}"
        )
        return
    log_writer.system(f"🔔 ACTION 요청: {runtime.get_agent_name(agent_id)} → {action_str[:80]}")
