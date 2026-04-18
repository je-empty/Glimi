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
    names = args.get("names", [])
    topic = args.get("topic", "")
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
    await yuna_edit_relationship(ctx.channel_obj, s)
    return {k: args[k] for k in ("name_a", "name_b", "field", "value")}


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
    if scene_id == "onboarding":
        if phase == "channels_setup":
            from src.scenes.onboarding.handlers import trigger_phase2
            await trigger_phase2(ctx.guild)
            return {"scene_id": scene_id, "phase": "channels_setup"}
        if phase == "complete":
            from src.scenes.onboarding.handlers import complete_onboarding
            await complete_onboarding()
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
        {"scene_id": "onboarding", "phase": "channels_setup"}, ctx
    )


async def _h_finish_onboarding(args: dict, ctx: ToolContext):
    # alias → scene_advance 위임
    return await _h_scene_advance(
        {"scene_id": "onboarding", "phase": "complete"}, ctx
    )


async def _h_create_agent_profile(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _cmd_profile_create
    await _cmd_profile_create(ctx.channel_obj, args["args"])
    return {"accepted": True}


async def _h_delete_agent_profile(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _cmd_profile_delete
    await _cmd_profile_delete(ctx.channel_obj, args["name"])
    return {"name": args["name"]}


async def _h_apply_avatar(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _apply_sample_avatar
    s = f"{args['name']} {args['avatar_filename']}"
    await _apply_sample_avatar(ctx.channel_obj, s, ctx.guild)
    return {"name": args["name"], "avatar": args["avatar_filename"]}


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
    cnt = args.get("count", 20)
    return {"result": await _run_query("로그", f"{args['target']} {cnt}", ctx)}


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
    # 중복 호출 차단 — 같은 caller가 같은 target에게 한 번 보낸 보고를 또 보내는 경우
    # (하나가 온보딩 리포트를 중복 전송해서 내부-dm이 어지러워지는 사례 방지).
    # 메시지 내용이 완전 다르면 허용 (caller가 의도적으로 후속 메시지 보낼 수 있음)이라
    # 직전 1건만 비교. meta key에 저장하고 helper에서 체크.
    dedup_key = f"request_dm:last:{ctx.caller_agent_id}:{target}"
    prev = db.get_meta(dedup_key) or ""
    cur_msg = args.get("message", "")
    # 너무 비슷한 내용 (80% 이상 prefix 동일) 재전송 차단
    if prev and _similar_prefix(prev, cur_msg, threshold=0.7):
        log_writer.system(
            f"[request_dm] {ctx.caller_agent_id} → {target} 중복 보고 스킵 "
            f"(prev='{prev[:40]}', cur='{cur_msg[:40]}')"
        )
        return {"skipped": True, "reason": "duplicate", "target": target}
    db.set_meta(dedup_key, cur_msg)
    s = json.dumps({
        "type": "DM",
        "target": target,
        "message": cur_msg,
    }, ensure_ascii=False)
    await _forward_action_to_yuna(ctx.caller_agent_id, s, ctx.guild)
    return {"forwarded_to": target}


def _similar_prefix(a: str, b: str, threshold: float = 0.7) -> bool:
    """두 문자열의 앞부분이 threshold 이상 겹치면 True. 정교한 유사도 계산 대신
    첫 30자 기준 Jaccard 유사도로 가볍게."""
    if not a or not b:
        return False
    al = a[:60].lower().replace(" ", "")
    bl = b[:60].lower().replace(" ", "")
    if not al or not bl:
        return False
    shorter = min(len(al), len(bl))
    match = sum(1 for i in range(shorter) if al[i] == bl[i])
    return (match / shorter) >= threshold


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
    "request_dev_task": _h_request_dev_task,
    "scene_advance": _h_scene_advance,
    "finish_profile_collection": _h_finish_profile_collection,
    "finish_onboarding": _h_finish_onboarding,
    "create_agent_profile": _h_create_agent_profile,
    "delete_agent_profile": _h_delete_agent_profile,
    "apply_avatar": _h_apply_avatar,
    "approve_request": _h_approve_request,
    # query
    "list_channels": _h_list_channels,
    "list_members": _h_list_members,
    "get_logs": _h_get_logs,
    "search_messages": _h_search_messages,
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
    # request
    "request_dm": _h_request_dm,
    "request_room": _h_request_room,
}


def register_all():
    """registry에 모든 핸들러 주입. 봇 시작 시 1회 호출."""
    for name, fn in _MAP.items():
        set_handler(name, fn)
