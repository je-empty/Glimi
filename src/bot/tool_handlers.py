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


async def _h_finish_profile_collection(args: dict, ctx: ToolContext):
    from src.bot.mgr_system import _trigger_onboarding_phase2
    await _trigger_onboarding_phase2(ctx.guild)
    return {"phase": "channels_setup"}


async def _h_finish_onboarding(args: dict, ctx: ToolContext):
    db.set_meta("onboarding_phase", "complete")
    log_writer.mark_onboarding_complete()
    log_writer.system("온보딩 최종 완료")
    return {"phase": "complete"}


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
    s = json.dumps({
        "type": "DM",
        "target": args["target"],
        "message": args["message"],
    }, ensure_ascii=False)
    await _forward_action_to_yuna(ctx.caller_agent_id, s, ctx.guild)
    return {"forwarded_to": args["target"]}


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
