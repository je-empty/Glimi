"""
Tool Handlers — 신규 tool protocol과 기존 yuna_*/execute_*/핸들러 함수들 연결 브릿지.

각 핸들러:
    async def handler(args: dict, ctx: ToolContext) -> dict | ToolResult

관례:
    성공 → dict 반환 (비면 {"ok": True})
    실패 → raise Exception → dispatcher가 fail ToolResult로 감쌈

등록:
    모듈 임포트 시점에 set_handler(name, fn) 호출로 registry에 주입.
"""
import json
from typing import Any

from src import db, log_writer
from src.core.tools.registry import set_handler
from src.core.tools.dispatcher import ToolContext


# ── 관리 도구 (mgr) ─────────────────────────────────────

async def _h_create_room(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_create_room
    from src.core.profile import get_user_name
    names = args.get("names", [])
    topic = args.get("topic", "")
    # Pre-check 중복 — guild 에 같은 이름의 채널 이미 있으면 skip 시그널을 LLM 에 명확히 반환.
    # 이전엔 tool_result 가 항상 {names, topic} 이라 유나가 skip 인지 모르고 반복 호출 (cycle #8: 12회).
    try:
        import discord as _discord
        # 채널명 후보 계산 — yuna_create_room 과 동일 로직의 압축판
        oc = get_user_name()
        agents = {a["name"]: a for a in db.list_agents()}
        has_owner = any(n == oc for n in names)
        participant_names = [n for n in names if n != oc and (n in agents or any(n in an for an in agents))]
        if not participant_names:
            # yuna_create_room 이 매칭 처리 — 그냥 전달
            pass
        else:
            if has_owner:
                prefix = "group"
            elif len(participant_names) == 2:
                prefix = "internal-dm"
            else:
                prefix = "internal-group"
            ch_name_a = f"{prefix}-{'-'.join(participant_names)}"
            ch_name_b = (f"{prefix}-{'-'.join(reversed(participant_names))}"
                         if len(participant_names) == 2 else None)
            existing = None
            if ctx.guild:
                existing = _discord.utils.get(ctx.guild.text_channels, name=ch_name_a)
                if not existing and ch_name_b:
                    existing = _discord.utils.get(ctx.guild.text_channels, name=ch_name_b)
            if existing:
                log_writer.system(f"[create_room] pre-check skip: #{existing.name}")
                return {"skipped": True, "reason": "already_exists",
                        "channel": existing.name, "names": names, "topic": topic}
    except Exception:
        pass
    args_str = f"{' '.join(names)} {topic}".strip()
    await yuna_create_room(ctx.channel_obj, args_str, ctx.guild)
    return {"names": names, "topic": topic}


async def _h_start_conversation(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_start_conversation
    names = args.get("names", [])
    situation = args.get("situation", "")
    args_str = f"{' '.join(names)} {situation}".strip()
    await yuna_start_conversation(ctx.channel_obj, args_str, ctx.guild)
    return {"names": names, "situation": situation}


async def _h_stop_conversation(args: dict, ctx: ToolContext):
    from src.core.conversation import stop_conversation, list_active_conversations
    from src.bot.core import send_as_agent
    from src.bot import MGR_ID
    target = args["target"].strip()
    if target == "전체":
        active = list_active_conversations()
        count = 0
        for c in active:
            stop_conversation(c["channel"])
            count += 1
        await send_as_agent(ctx.channel_obj, MGR_ID, f"전체 대화 {count}건 중단했어")
        return {"stopped": count}
    if stop_conversation(target):
        await send_as_agent(ctx.channel_obj, MGR_ID, f"#{target} 대화 중단했어")
        return {"stopped": target}
    await send_as_agent(ctx.channel_obj, MGR_ID, f"#{target}에 진행 중인 대화 없어")
    return {"stopped": None, "reason": "not running"}


async def _h_invite_owner(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_invite_owner
    await yuna_invite_owner(ctx.channel_obj, args["target"], ctx.guild)
    return {"target": args["target"]}


async def _h_delete_channel(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_delete_channel
    await yuna_delete_channel(ctx.channel_obj, args["target"], ctx.guild)
    return {"target": args["target"]}


async def _h_rename_channel(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_rename_channel
    s = f"{args['target']} {args['value']}"
    await yuna_rename_channel(ctx.channel_obj, s, ctx.guild)
    return {"from": args["target"], "to": args["value"]}


async def _h_set_topic(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_set_channel_topic
    s = f"{args['target']} {args['value']}"
    await yuna_set_channel_topic(ctx.channel_obj, s, ctx.guild)
    return {"target": args["target"], "topic": args["value"]}


async def _h_purge_messages(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_purge_messages
    cnt = args.get("count", 100)
    s = f"{args['target']} {cnt}"
    await yuna_purge_messages(ctx.channel_obj, s, ctx.guild)
    return {"target": args["target"], "count": cnt}


async def _h_recover_channel(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_restore_discord
    await yuna_restore_discord(ctx.channel_obj, args["target"], ctx.guild)
    return {"target": args["target"]}


async def _h_set_emotion(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_change_emotion
    s = f"{args['name']} {args['emotion']} {args['intensity']}"
    await yuna_change_emotion(ctx.channel_obj, s)
    return {"name": args["name"], "emotion": args["emotion"], "intensity": args["intensity"]}


async def _h_update_profile(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_edit_profile
    s = f"{args['name']} {args['field']} {args['value']}"
    await yuna_edit_profile(ctx.channel_obj, s)
    return {"name": args["name"], "field": args["field"], "value": args["value"]}


async def _h_update_relationship(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_edit_relationship
    s = f"{args['name_a']} {args['name_b']} {args['field']} {args['value']}"
    # caller_agent_id 전달 — self-modification guard 가 이걸 보고 차단 여부 판정.
    result = await yuna_edit_relationship(ctx.channel_obj, s, caller_agent_id=ctx.caller_agent_id or "")
    base = {k: args[k] for k in ("name_a", "name_b", "field", "value")}
    if isinstance(result, dict):
        base.update(result)
    return base


async def _h_invoke_agent(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_force_agent
    s = json.dumps({
        "name": args["name"],
        "target": args["target"],
        "instruction": args["instruction"],
    }, ensure_ascii=False)
    await yuna_force_agent(ctx.channel_obj, s, ctx.guild)
    return {"name": args["name"], "target": args["target"]}


async def _h_reset_channel(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_wipe_channel
    await yuna_wipe_channel(ctx.channel_obj, args["target"], ctx.guild)
    return {"target": args["target"]}


async def _h_clear_messages(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_delete_messages
    s = args.get("target", "") if args.get("mode") == "채널" else "전체"
    await yuna_delete_messages(ctx.channel_obj, s)
    return {"mode": args["mode"], "target": args.get("target")}


async def _h_reset_agent(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_wipe_agent
    await yuna_wipe_agent(ctx.channel_obj, args["name"])
    return {"name": args["name"]}


async def _h_revive_persona(args: dict, ctx: ToolContext):
    """메타 박살된 페르소나 부활."""
    target = db.get_agent_by_name(args["name"])
    if not target:
        return {"name": args["name"], "ok": False, "error": "agent not found"}
    result = db.revive_meta_breached(target["id"])
    if result.get("restored"):
        log_writer.system(
            f"🌱 [부활] {args['name']} ({target['id']}) — 자각 상태로 부활. "
            f"이전 박살: {result.get('was_breached')}"
        )
        # runtime cache invalidate — 새 status 반영
        try:
            from src.core import runtime as _rt
            if hasattr(_rt, "invalidate_cache"):
                _rt.invalidate_cache(target["id"])
        except Exception:
            pass
    return {"name": args["name"], "ok": result.get("restored", False),
            "was_breached": result.get("was_breached", False)}


async def _h_request_dev_task(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_dev_request
    from src.bot import MGR_ID
    await yuna_dev_request(ctx.channel_obj, args["args"], MGR_ID)
    return {"accepted": True}


async def _h_scene_advance(args: dict, ctx: ToolContext):
    """범용 씬 phase 전환. scene_id + phase 조합별로 적절한 handler 호출."""
    from src.scenes import get_scene
    scene_id = args.get("scene_id", "").strip()
    phase = args.get("phase", "").strip()
    if not scene_id or not phase:
        return {"ok": False, "reason": "scene_id + phase 필수"}
    scene = get_scene(scene_id)
    if scene is None:
        return {"ok": False, "reason": f"unknown scene: {scene_id}"}

    # 씬별 특수 핸들러 위임 (채널 생성 등 side-effect 포함 단계)
    if scene_id == "tutorial":
        if phase == "channels_setup":
            from src.scenes.tutorial.handlers import trigger_phase2
            await trigger_phase2(ctx.guild)
            return {"scene_id": scene_id, "phase": "channels_setup"}
        if phase == "complete":
            from src.scenes.tutorial.handlers import complete_tutorial
            await complete_tutorial()
            return {"scene_id": scene_id, "phase": "complete"}

    # 기본: 씬 phase만 업데이트 (side-effect 없는 단순 전환)
    scene.set_phase(phase)
    from src.core.runtime import runtime
    from src.bot import MGR_ID
    runtime.refresh_agent(MGR_ID)
    return {"scene_id": scene_id, "phase": phase}


async def _h_finish_profile_collection(args: dict, ctx: ToolContext):
    # alias → scene_advance 위임
    return await _h_scene_advance(
        {"scene_id": "tutorial", "phase": "channels_setup"}, ctx
    )


async def _h_finish_tutorial(args: dict, ctx: ToolContext):
    # Guard: persona 가 0 개면 '결함 있는 완료' — Hana 가 create_agent_profile 실패했는데
    # '만들었어' 보고만 보내서 유나가 finish_tutorial 호출하는 케이스 방지.
    try:
        personas = db.list_agents("persona")
    except Exception:
        personas = []
    if not personas:
        log_writer.system(
            "[finish_tutorial] 거부 — persona 0개. Hana 의 create_agent_profile 이 "
            "실제로 성공했는지 확인하고 재시도."
        )
        return {
            "rejected": True,
            "reason": "no_persona_exists",
            "note": (
                "튜토리얼 완료 조건 미달: persona 에이전트가 1개도 없음. "
                "Hana (creator) 가 create_agent_profile 을 다시 호출해야 함. "
                "args 필드에 JSON 문자열 전달 누락 여부 확인."
            ),
        }
    return await _h_scene_advance(
        {"scene_id": "tutorial", "phase": "complete"}, ctx
    )


async def _h_create_agent_profile(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _cmd_profile_create
    # 중복 생성 체크 — LLM 에게 확실한 시그널 돌려줘서 tool chain 멈추게 함.
    # 이전엔 Creator 가 한 턴에 중복 create (같은 persona 두 번 생성 + "만들었어" 보고 2번 +
    # 이미지 preview 재전송) 사례. DB/Discord side-effect 다 일어나서 UX 혼란.
    try:
        import json as _j
        raw = args.get("args", "")
        payload = _j.loads(raw) if isinstance(raw, str) else raw
        new_name = (payload or {}).get("name")
    except Exception:
        payload, new_name = None, None
    if new_name:
        existing = db.get_agent_by_name(new_name)
        if existing and existing.get("type") == "persona":
            log_writer.system(
                f"[create_agent_profile] duplicate '{new_name}' — skip "
                f"(existing id={existing['id']})"
            )
            # LLM 이 이 결과 보고 "아 이미 있네" 인식 → 후속 request_dm / 이미지 preview 안 함
            return {"accepted": False, "reason": "already_exists",
                    "existing_id": existing["id"], "name": new_name}

    await _cmd_profile_create(ctx.channel_obj, args["args"])
    # 이벤트 로그 — 새 멤버 합류
    try:
        db.log_event("멤버합류", ["owner", new_name or "새친구"],
                     f"{new_name or '새친구'} 합류 (MBTI: {(payload or {}).get('mbti', '?')}, "
                     f"관계: {((payload or {}).get('relationship_to_owner') or {}).get('type', '?')})",
                     impact="긍정")
    except Exception:
        pass
    return {"accepted": True}


async def _h_delete_agent_profile(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _cmd_profile_delete
    await _cmd_profile_delete(ctx.channel_obj, args["name"])
    return {"name": args["name"]}


async def _h_set_profile_image(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _apply_sample_profile_image
    from src.bot.profile_preview import get_recent_preview, clear_preview
    # 중복 방지 — 같은 sample 로 이미 적용된 persona 면 skip.
    # 비교 대상은 `sample_source_file` (apply 성공 후에만 set) — `profile_image_filename`
    # 은 create_agent_profile JSON 에 LLM 이 sample 파일명을 그대로 집어넣는 케이스가
    # 있어서 "skip 했는데 실제 apply 는 한 번도 안 된" 회귀 발생.
    requested = args["profile_image_filename"]
    channel_name = getattr(ctx.channel_obj, "name", "") or ""
    previewed = get_recent_preview(ctx.caller_agent_id or "", channel_name)
    # creator 가 직전에 채널에 띄운 sample 과 다른 파일명을 LLM 이 넘긴 경우 preview 우선.
    # preview 가 있으면 owner 가 이미 그 얼굴을 보고 동의한 것 — 그 파일이 진실.
    if previewed and previewed != requested:
        log_writer.system(
            f"[set_profile_image] preview 와 mismatch — '{requested}' → '{previewed}' 로 교정"
        )
        requested = previewed
    target_agent = db.get_agent_by_name(args["name"])
    if target_agent and target_agent.get("sample_source_file") == requested:
        log_writer.system(
            f"[set_profile_image] skip — {args['name']} 이미 {requested} 적용됨"
        )
        clear_preview(ctx.caller_agent_id or "", channel_name)
        return {"name": args["name"], "profile_image": requested,
                "skipped": True, "reason": "already_set"}
    s = f"{args['name']} {requested}"
    await _apply_sample_profile_image(ctx.channel_obj, s, ctx.guild,
                               caller_agent_id=ctx.caller_agent_id)
    clear_preview(ctx.caller_agent_id or "", channel_name)
    return {"name": args["name"], "profile_image": requested}


async def _h_approve_request(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import yuna_approve_action
    s = json.dumps({
        "request_id": args["request_id"],
        "decision": args["decision"],
        "reason": args.get("reason", ""),
    }, ensure_ascii=False)
    await yuna_approve_action(ctx.channel_obj, s, ctx.guild)
    return {"request_id": args["request_id"], "decision": args["decision"]}


# ── 조회 도구 ──────────────────────────────────────────

async def _run_query(name: str, args_str: str, ctx: ToolContext) -> str:
    """기존 execute_yuna_query 래퍼 — 레거시 cmd 이름으로 위임"""
    from src.bot.mgr_system import execute_yuna_query
    # 기존 QUERY는 "cmd args_str" 포맷 또는 JSON
    payload = f"{name} {args_str}".strip() if args_str else name
    return await execute_yuna_query(payload, ctx.guild)


async def _h_list_channels(args, ctx):
    return {"result": await _run_query("채널목록", "", ctx)}


async def _h_list_members(args, ctx):
    return {"result": await _run_query("멤버목록", "", ctx)}


async def _h_get_logs(args, ctx):
    # 시간 범위 파라미터가 있으면 db 레벨에서 직접 조회 (컨텍스트 절약).
    # 없으면 레거시 execute_yuna_query("로그", ...) 경로 (최근 N건).
    target = args["target"]
    since_min = args.get("since_minutes")
    from_time = args.get("from_time")
    to_time = args.get("to_time")
    limit = args.get("limit", 200)

    if since_min or from_time or to_time:
        from src import db as _db
        rows = _db.get_messages_in_range(
            channel=target,
            since=from_time or None,
            until=to_time or None,
            since_minutes=since_min,
            limit=int(limit) if limit else 200,
        )
        if not rows:
            return {"result": f"[{target}] 해당 범위 메시지 없음"}
        # 채널명: 타임 hh:mm speaker: msg 형태 압축
        from src.core.profile import get_user_id, get_user_name
        from src.core.runtime import runtime as _rt
        uid = get_user_id()
        lines = []
        for r in rows:
            ts = r.get("timestamp", "")
            hhmm = ts[11:16] if len(ts) >= 16 else ts
            sp = r.get("speaker", "?")
            name = get_user_name() if sp == uid else _rt.get_agent_name(sp)
            msg = (r.get("message") or "").replace("\n", " ")
            if len(msg) > 200:
                msg = msg[:200] + "…"
            lines.append(f"{hhmm} {name}: {msg}")
        header = f"[{target} {len(rows)}건"
        if since_min:
            header += f", 최근 {since_min}분"
        elif from_time or to_time:
            header += f", {from_time or '처음'} ~ {to_time or '지금'}"
        header += "]"
        return {"result": header + "\n" + "\n".join(lines)}

    cnt = args.get("count", 20)
    return {"result": await _run_query("로그", f"{target} {cnt}", ctx)}


async def _h_get_tool_details(args, ctx):
    from src.core.tools.reference import build_tool_details
    return {"result": build_tool_details(args["name"])}


async def _h_query_knowledge(args, ctx):
    from src import knowledge as _kb
    return {"result": _kb.query(args["topic"], ctx.caller_agent_id)}


async def _h_search_messages(args, ctx):
    return {"result": await _run_query("검색", args["args"], ctx)}


async def _h_get_speaker_history(args, ctx):
    return {"result": await _run_query("발화", args["name"], ctx)}


async def _h_get_profile(args, ctx):
    return {"result": await _run_query("프로필", args["name"], ctx)}


async def _h_get_relationships(args, ctx):
    return {"result": await _run_query("관계", "", ctx)}


async def _h_get_events(args, ctx):
    return {"result": await _run_query("이벤트", "", ctx)}


async def _h_discord_get_logs(args, ctx):
    cnt = args.get("count", 50)
    return {"result": await _run_query("디코로그", f"{args['target']} {cnt}", ctx)}


async def _h_discord_list_channels(args, ctx):
    return {"result": await _run_query("디코채널목록", "", ctx)}


async def _h_discord_list_members(args, ctx):
    return {"result": await _run_query("디코멤버", "", ctx)}


async def _h_discord_get_channel_info(args, ctx):
    return {"result": await _run_query("디코채널정보", args["target"], ctx)}


async def _h_discord_get_server(args, ctx):
    return {"result": await _run_query("디코서버", "", ctx)}


async def _h_discord_get_pins(args, ctx):
    return {"result": await _run_query("디코핀", args["target"], ctx)}


# ── 요청 도구 (persona → mgr) ──────────────────────────

async def _h_request_dm(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _forward_action_to_yuna
    target = args["target"]
    cur_msg = args.get("message", "") or ""

    # Self-target 방어 — LLM 이 자기 이름을 target 으로 호출하는 버그 케이스 (QA 관찰).
    # caller 의 display_name 과 target 이 같으면 drop + 명확한 사유 반환.
    try:
        caller_profile = db.get_agent(ctx.caller_agent_id) or {}
        caller_name = caller_profile.get("name", "")
    except Exception:
        caller_name = ""
    if caller_name and target.strip() == caller_name:
        log_writer.system(
            f"[request_dm] self-target 차단: {ctx.caller_agent_id}({caller_name}) → {target}"
        )
        return {
            "rejected": True,
            "reason": "self_target",
            "target": target,
            "note": f"본인({caller_name}) 에게 request_dm 을 보낼 순 없음. target 은 다른 에이전트여야 함.",
        }

    # 중복 호출 차단 — 이중 방어:
    #   (a) 최근 180초 내 유사 메시지 (threshold 0.80) → skip
    #   (b) 최근 180초 내 같은 target 에 **3회 이상** 호출 → 무조건 skip (내용 무관)
    # 과거엔 60초/0.95 라 유나가 test_user "ㅇㅇ!" 확인 응답마다 미묘히 다른 문구로 request_dm
    # 재발사해서 하나한테 똑같은 요청 20+ 회 반복 (2026-04-23 QA 관찰). 시간창 확장 + 타겟
    # 단위 호출 빈도 카운트로 강화.
    import time as _time
    import json as _json
    dedup_key = f"request_dm:last:{ctx.caller_agent_id}:{target}"
    count_key = f"request_dm:count:{ctx.caller_agent_id}:{target}"
    prev_raw = db.get_meta(dedup_key) or ""
    try:
        prev_obj = _json.loads(prev_raw) if prev_raw else {}
    except Exception:
        prev_obj = {}
    prev_msg = prev_obj.get("msg", "") if isinstance(prev_obj, dict) else ""
    prev_ts = prev_obj.get("ts", 0) if isinstance(prev_obj, dict) else 0
    now = _time.time()
    within_window = (now - prev_ts) < 180  # 180초 (3분) 로 확장
    if within_window and prev_msg and _similar_prefix(prev_msg, cur_msg, threshold=0.80):
        log_writer.system(
            f"[request_dm] {ctx.caller_agent_id} → {target} 3분 내 유사 메시지 스킵 "
            f"(prev='{prev_msg[:40]}', cur='{cur_msg[:40]}')"
        )
        return {
            "skipped": True,
            "reason": "similar_message_within_3min",
            "target": target,
            "note": "최근 3분 내 비슷한 메시지를 이미 보냈다. 하나 응답 기다리지 말고 재촉 금지.",
        }

    # (b) 타겟 단위 호출 빈도 체크 — 같은 target 에 180초 내 3회+ 호출 시 강제 skip
    count_raw = db.get_meta(count_key) or ""
    try:
        count_obj = _json.loads(count_raw) if count_raw else {}
    except Exception:
        count_obj = {}
    timestamps = count_obj.get("ts_list", []) if isinstance(count_obj, dict) else []
    # 180초 창 밖 타임스탬프는 버림
    timestamps = [t for t in timestamps if (now - t) < 180]
    if len(timestamps) >= 3:
        log_writer.system(
            f"[request_dm] {ctx.caller_agent_id} → {target} 3분 내 {len(timestamps)}회 연속 호출 — 강제 차단"
        )
        return {
            "skipped": True,
            "reason": "too_frequent_same_target",
            "target": target,
            "note": f"{target}에게 3분 내 {len(timestamps)}번 보냄. 응답 올 때까지 기다려. test_user 의 확인성 답변에 또 도구 호출 하지 마.",
        }
    timestamps.append(now)
    db.set_meta(count_key, _json.dumps({"ts_list": timestamps}, ensure_ascii=False))
    db.set_meta(dedup_key, _json.dumps({"msg": cur_msg, "ts": now}, ensure_ascii=False))
    s = _json.dumps({
        "type": "DM",
        "target": target,
        "message": cur_msg,
    }, ensure_ascii=False)
    await _forward_action_to_yuna(ctx.caller_agent_id, s, ctx.guild)
    try:
        db.log_event("dm_request", [ctx.caller_agent_id, target],
                     f"{ctx.caller_agent_id}가 {target}한테 DM 요청: {cur_msg[:60]}",
                     impact="중립")
    except Exception:
        pass
    return {"forwarded_to": target}


def _similar_prefix(a: str, b: str, threshold: float = 0.95) -> bool:
    """두 문자열의 앞부분이 threshold 이상 겹치면 True. 60자 기준 문자별 일치율."""
    if not a or not b:
        return False
    al = a[:60].lower().replace(" ", "")
    bl = b[:60].lower().replace(" ", "")
    if not al or not bl:
        return False
    shorter = min(len(al), len(bl))
    match = sum(1 for i in range(shorter) if al[i] == bl[i])
    return (match / shorter) >= threshold


async def _h_recall_memory(args: dict, ctx: ToolContext):
    """에이전트가 자기 기억을 deep search. caller_agent_id의 기억을 뒤짐."""
    from src.core.memory import recall_memory
    results = recall_memory(
        agent_id=ctx.caller_agent_id,
        query=args.get("query", "") or "",
        entity=args.get("entity", "") or "",
        time_range_days=args.get("time_range_days"),
        limit=int(args.get("limit") or 10),
    )
    return {"count": len(results), "results": results}


async def _h_pin_memory(args: dict, ctx: ToolContext):
    """유나가 target_agent의 기억 한 건을 고정/해제."""
    from src.core.memory import pin_memory
    name = str(args.get("target_agent") or "").strip()
    if not name:
        raise ValueError("target_agent 필요")
    a = db.get_agent_by_name(name)
    if not a:
        raise ValueError(f"멤버 '{name}' 없음")
    memory_id = int(args["memory_id"])
    pinned_flag = args.get("pinned", 1)
    pinned = bool(int(pinned_flag)) if pinned_flag is not None else True
    result = pin_memory(memory_id, pinned=pinned, reason=args.get("reason", ""))
    # owner 검증 — 해당 기억이 지정한 에이전트 것인지
    if result.get("ok") and result.get("agent_id") != a["id"]:
        # rollback
        pin_memory(memory_id, pinned=not pinned)
        raise ValueError(
            f"memory_id={memory_id}는 {name}의 기억이 아님 (owner={result.get('agent_id')})"
        )
    return result


async def _h_request_room(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _forward_action_to_yuna
    s = json.dumps({
        "type": "톡방",
        "names": args.get("names", []),
        "topic": args.get("topic", ""),
    }, ensure_ascii=False)
    await _forward_action_to_yuna(ctx.caller_agent_id, s, ctx.guild)
    return {"names": args.get("names", []), "topic": args.get("topic", "")}


# ── 레지스트리 주입 ────────────────────────────────────

_MAP = {
    # management
    "create_room": _h_create_room,
    "start_conversation": _h_start_conversation,
    "stop_conversation": _h_stop_conversation,
    "invite_owner": _h_invite_owner,
    "delete_channel": _h_delete_channel,
    "rename_channel": _h_rename_channel,
    "set_topic": _h_set_topic,
    "purge_messages": _h_purge_messages,
    "recover_channel": _h_recover_channel,
    "set_emotion": _h_set_emotion,
    "update_profile": _h_update_profile,
    "update_relationship": _h_update_relationship,
    "invoke_agent": _h_invoke_agent,
    "reset_channel": _h_reset_channel,
    "clear_messages": _h_clear_messages,
    "reset_agent": _h_reset_agent,
    "revive_persona": _h_revive_persona,
    "request_dev_task": _h_request_dev_task,
    "scene_advance": _h_scene_advance,
    "finish_profile_collection": _h_finish_profile_collection,
    "finish_tutorial": _h_finish_tutorial,
    "create_agent_profile": _h_create_agent_profile,
    "delete_agent_profile": _h_delete_agent_profile,
    "set_profile_image": _h_set_profile_image,
    "approve_request": _h_approve_request,
    "pin_memory": _h_pin_memory,
    # query
    "list_channels": _h_list_channels,
    "list_members": _h_list_members,
    "get_logs": _h_get_logs,
    "search_messages": _h_search_messages,
    "get_tool_details": _h_get_tool_details,
    "query_knowledge": _h_query_knowledge,
    "get_speaker_history": _h_get_speaker_history,
    "get_profile": _h_get_profile,
    "get_relationships": _h_get_relationships,
    "get_events": _h_get_events,
    "discord_get_logs": _h_discord_get_logs,
    "discord_list_channels": _h_discord_list_channels,
    "discord_list_members": _h_discord_list_members,
    "discord_get_channel_info": _h_discord_get_channel_info,
    "discord_get_server": _h_discord_get_server,
    "discord_get_pins": _h_discord_get_pins,
    "recall_memory": _h_recall_memory,
    # request
    "request_dm": _h_request_dm,
    "request_room": _h_request_room,
}


def register_all():
    """registry에 모든 핸들러 주입. 봇 시작 시 1회 호출."""
    for name, fn in _MAP.items():
        set_handler(name, fn)
