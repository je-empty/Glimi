# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
Tool Handlers (core) — discord-free tool-protocol handler registry.

The neutral home of the old ``community/bot/tool_handlers.py``: each handler is
``async def handler(args: dict, ctx: ToolContext) -> dict | ToolResult`` and routes
channel I/O through ``ctx.channels`` (a :class:`ChannelAdapter`) +
``community.core.mgr_actions`` + ``community.core.dev_agent`` — NEVER ``import
discord`` and NEVER ``community.bot.*`` at module level.

Differences vs the legacy bot registry:
- ``ctx.channel_obj`` / ``ctx.guild`` → ``ctx.channels`` (find/ensure/send/avatar).
- the ``discord_*`` query handlers (디코*) are DROPPED — no web analog.
- ``yuna_*`` delegations target ``core.mgr_actions`` (adapter signatures).

The legacy ``bot/tool_handlers.py`` re-exports ``register_all`` from here so the
(Phase-6-doomed) Discord transport keeps registering the same handler set.
"""
from __future__ import annotations

import json

from community import db, log_writer
from glimi.tools.registry import set_handler
from glimi.tools.dispatcher import ToolContext
from community.core.channels import MGR_ID, DEV_CHANNEL, DEV_ID


# ── 관리 도구 (mgr) — delegate to core.mgr_actions (adapter-routed) ─────────

async def _h_create_room(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_create_room
    names = args.get("names", [])
    topic = args.get("topic", "")
    args_str = " ".join(names) + (f" {topic}" if topic else "")
    # 중복 사전체크 — 같은 이름쌍 채널이 이미 있으면 skip (어댑터 find_channel)
    if len(names) == 2:
        ch_a = f"internal-dm-{names[0]}-{names[1]}"
        ch_b = f"internal-dm-{names[1]}-{names[0]}"
        if await ctx.channels.find_channel(ch_a) or await ctx.channels.find_channel(ch_b):
            return {"names": names, "topic": topic, "skipped": True, "reason": "already_exists"}
    await yuna_create_room(ctx.channel_name, args_str, ctx)
    return {"names": names, "topic": topic}


async def _h_start_conversation(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_start_conversation
    names = args.get("names", [])
    context = args.get("context", "")
    args_str = " ".join(names) + (f" {context}" if context else "")
    await yuna_start_conversation(ctx.channel_name, args_str, ctx)
    return {"names": names}


async def _h_stop_conversation(args: dict, ctx: ToolContext):
    from community.core.conversation_bridge import stop_conversation, list_active_conversations
    target = args.get("target", "all")
    if target == "all":
        active = list_active_conversations()
        count = 0
        for ch in list(active):
            if stop_conversation(ch):
                count += 1
        await ctx.channels.send_as_agent(ctx.channel_name, MGR_ID, f"전체 대화 {count}건 중단했어")
        return {"stopped": count}
    if stop_conversation(target):
        await ctx.channels.send_as_agent(ctx.channel_name, MGR_ID, f"#{target} 대화 중단했어")
        return {"stopped": target}
    await ctx.channels.send_as_agent(ctx.channel_name, MGR_ID, f"#{target}에 진행 중인 대화 없어")
    return {"stopped": None}


async def _h_delete_channel(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_delete_channel
    await yuna_delete_channel(ctx.channel_name, args["target"], ctx)
    return {"target": args["target"]}


async def _h_rename_channel(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_rename_channel
    s = f"{args['target']} {args['new_name']}"
    await yuna_rename_channel(ctx.channel_name, s, ctx)
    return {"target": args["target"], "new_name": args["new_name"]}


async def _h_set_topic(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_set_channel_topic
    s = f"{args['target']} {args['topic']}"
    await yuna_set_channel_topic(ctx.channel_name, s, ctx)
    return {"target": args["target"], "topic": args["topic"]}


async def _h_purge_messages(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_delete_messages
    cnt = args.get("count", 10)
    await yuna_delete_messages(ctx.channel_name, f"{args['target']} {cnt}", ctx)
    return {"target": args["target"], "count": cnt}


async def _h_set_emotion(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_change_emotion
    s = f"{args['name']} {args['emotion']} {args.get('intensity', 5)}"
    await yuna_change_emotion(ctx.channel_name, s, ctx)
    return {"name": args["name"], "emotion": args["emotion"]}


async def _h_update_profile(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_edit_profile
    s = f"{args['name']} {args['field']} {args['value']}"
    await yuna_edit_profile(ctx.channel_name, s, ctx)
    return {"name": args["name"], "field": args["field"]}


async def _h_update_relationship(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_edit_relationship
    s = json.dumps(args, ensure_ascii=False)
    result = await yuna_edit_relationship(ctx.channel_name, s, ctx,
                                          caller_agent_id=ctx.caller_agent_id or "")
    return result if isinstance(result, dict) else {"ok": True}


async def _h_invoke_agent(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_force_agent
    s = f"{args['name']} {args['target']} {args['instruction']}"
    await yuna_force_agent(ctx.channel_name, s, ctx)
    return {"name": args["name"], "target": args["target"]}


async def _h_reset_channel(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_wipe_channel
    await yuna_wipe_channel(ctx.channel_name, args["target"], ctx)
    return {"target": args["target"]}


async def _h_clear_messages(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_delete_messages
    cnt = args.get("count", 10)
    await yuna_delete_messages(ctx.channel_name, f"{args['target']} {cnt}", ctx)
    return {"target": args["target"], "count": cnt}


async def _h_reset_agent(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import yuna_wipe_agent
    await yuna_wipe_agent(ctx.channel_name, args["name"], ctx)
    return {"name": args["name"]}


async def _h_revive_persona(args: dict, ctx: ToolContext):
    """메타 박살된 페르소나 부활 (DB only)."""
    target = db.get_agent_by_name(args["name"])
    if not target:
        return {"name": args["name"], "ok": False, "error": "agent not found"}
    result = db.revive_meta_breached(target["id"])
    if result.get("restored"):
        log_writer.system(
            f"🌱 [부활] {args['name']} ({target['id']}) — 자각 상태로 부활. "
            f"이전 박살: {result.get('was_breached')}"
        )
        try:
            from community.core import runtime as _rt
            if hasattr(_rt, "invalidate_cache"):
                _rt.invalidate_cache(target["id"])
        except Exception:
            pass
    return {"name": args["name"], "ok": result.get("restored", False),
            "was_breached": result.get("was_breached", False)}


# ── dev queue 도구 (DB-backed via core.dev_agent) ───────────────────────────

async def _h_request_dev_task(args: dict, ctx: ToolContext):
    """레거시 — pending.json 생성 (web: queue insert only, no bot.close)."""
    from community.core.mgr_actions import create_dev_request
    create_dev_request(args["args"], ctx.caller_agent_id or MGR_ID)
    return {"accepted": True}


async def _h_request_dev_fix(args: dict, ctx: ToolContext):
    """매니저/오너 호출 — dev_requests 큐 적재 + dev 봇 lazy seed (adapter-routed)."""
    from community.core.dev_agent import (
        ensure_dev_seeded, enqueue_dev_request, find_similar_recent_request,
    )
    from community import community as _community

    required = ("channel", "severity", "repro", "expected", "actual")
    missing = [k for k in required if not args.get(k) or not str(args[k]).strip()]
    if missing:
        return {"ok": False, "reason": f"missing fields: {missing}"}
    if args["severity"] not in ("low", "med", "high"):
        return {"ok": False, "reason": "severity must be one of low/med/high"}

    payload = {
        "channel": str(args["channel"]).strip(),
        "severity": args["severity"],
        "repro": str(args["repro"]).strip(),
        "expected": str(args["expected"]).strip(),
        "actual": str(args["actual"]).strip(),
        "notes": str(args.get("notes", "")).strip(),
    }
    requested_by = ctx.caller_agent_id or "owner"
    community_id = _community.get_community_id() or "unknown"

    existing = find_similar_recent_request(community_id, payload, window_minutes=60)
    if existing:
        log_writer.system(
            f"[dev] dedup hit — 기존 #{existing['id']} 와 같은 channel/severity, 새 요청 거절"
        )
        return {
            "ok": False, "reason": "duplicate_recent_request",
            "existing_request_id": existing["id"], "existing_status": existing["status"],
            "hint": "같은 채널·심각도의 최근 요청이 이미 큐에 있어.",
        }

    seeded_now = ensure_dev_seeded()

    # dev (세나) DM 채널 ensure (transport-neutral)
    try:
        await ctx.channels.ensure_channel(DEV_CHANNEL, participants=[DEV_ID, MGR_ID])
        db.set_channel_participants(DEV_CHANNEL, [DEV_ID, MGR_ID])
    except Exception as e:
        log_writer.system(f"[dev] ⚠ {DEV_CHANNEL} 채널 ensure 실패: {type(e).__name__}: {e}")

    request_id = enqueue_dev_request(community_id, requested_by, payload)

    if requested_by != "owner":
        try:
            sev_label = {"low": "낮음", "med": "보통", "high": "높음"}.get(payload["severity"], payload["severity"])
            short_repro = payload["repro"][:80] + ("…" if len(payload["repro"]) > 80 else "")
            short_actual = payload["actual"][:80] + ("…" if len(payload["actual"]) > 80 else "")
            report_msg = (
                f"[버그 #{request_id}] {sev_label} · #{payload['channel']}\n"
                f"증상: {short_repro}\n실제: {short_actual}"
            )
            await ctx.channels.send_as_agent(DEV_CHANNEL, requested_by, report_msg, paced=False)
        except Exception as e:
            log_writer.system(f"[dev] ⚠ 보고 post 실패 (#{request_id}): {type(e).__name__}: {e}")

    if seeded_now:
        try:
            from community.core import runtime as _rt
            if hasattr(_rt, "invalidate_cache"):
                _rt.invalidate_cache(DEV_ID)
        except Exception:
            pass

    return {
        "ok": True, "request_id": request_id, "community_id": community_id,
        "dispatched_to": "한세나", "channel": DEV_CHANNEL,
    }


async def _h_dev_organize(args: dict, ctx: ToolContext):
    """Dev (세나) 전용 — pending → analyzed (DB only; files_hint 환각 검증)."""
    from community.core.dev_agent import DEV_ID as _DEV_ID, get_request, mark_analyzed
    from pathlib import Path as _Path

    if ctx.caller_agent_id != _DEV_ID:
        return {"ok": False, "reason": "only dev agent can call dev_organize"}

    request_id = args.get("request_id")
    task_brief = (args.get("task_brief") or "").strip()
    sera_summary = (args.get("sera_summary") or "").strip()
    analysis_notes = (args.get("analysis_notes") or "").strip()
    confidence = args.get("confidence", "")
    files_hint = args.get("files_hint") or []
    if not isinstance(request_id, int) or not task_brief or not sera_summary:
        return {"ok": False, "reason": "request_id + task_brief + sera_summary required"}
    if confidence not in ("high", "low"):
        return {"ok": False, "reason": "confidence must be 'high' or 'low'"}

    req = get_request(request_id)
    if not req:
        return {"ok": False, "reason": f"request #{request_id} not found"}
    if req["status"] != "pending":
        return {"ok": False, "reason": f"request #{request_id} status is {req['status']}, not pending"}

    # files_hint 환각 검증 — community 패키지 루트 기준.
    project_root = _Path(__file__).resolve().parent.parent.parent  # core/X.py → community pkg parent
    real_files: list[str] = []
    hallucinated: list[str] = []
    for p in files_hint:
        if not isinstance(p, str) or not p.strip():
            continue
        rel = p.strip().lstrip("./")
        if rel.startswith("/"):
            hallucinated.append(p)
            continue
        full = project_root / rel
        if full.exists() and full.is_file():
            real_files.append(rel)
        else:
            hallucinated.append(p)

    extra_notes = ""
    if hallucinated:
        extra_notes = (
            f"\n\n[validator] files_hint 검증 — 존재하지 않는 경로 strip 됨: "
            f"{', '.join(hallucinated)}. admin 검토 시 실제 코드베이스 grep 필수."
        )
        log_writer.system(
            f"[dev] #{request_id} files_hint 환각 {len(hallucinated)}건 strip "
            f"(real={len(real_files)}, hallucinated={hallucinated})"
        )
    if files_hint and not real_files:
        confidence = "low"
        extra_notes += "\n[validator] 모든 files_hint 경로가 환각 — confidence 강제 down."

    final_notes = (analysis_notes + extra_notes).strip()
    mark_analyzed(request_id, task_brief, real_files, final_notes, sera_summary, confidence)
    return {
        "ok": True, "request_id": request_id, "status": "analyzed", "confidence": confidence,
        "files_hint_real": real_files, "files_hint_hallucinated": hallucinated,
    }


async def _h_dev_escalate(args: dict, ctx: ToolContext):
    from community.core.dev_agent import DEV_ID as _DEV_ID, get_request, mark_needs_human_review
    if ctx.caller_agent_id != _DEV_ID:
        return {"ok": False, "reason": "only dev agent can call dev_escalate"}
    request_id = args.get("request_id")
    summary = (args.get("summary") or "").strip()
    decision_points = args.get("decision_points") or []
    if not isinstance(request_id, int) or not summary or not decision_points:
        return {"ok": False, "reason": "request_id + summary + decision_points required"}
    req = get_request(request_id)
    if not req:
        return {"ok": False, "reason": f"request #{request_id} not found"}
    if req["status"] != "pending":
        return {"ok": False, "reason": f"request #{request_id} status is {req['status']}"}
    report = {
        "summary": summary, "decision_points": decision_points,
        "suggested_options": args.get("suggested_options") or [],
        "context_files": args.get("context_files") or [],
        "severity": args.get("severity", "med"),
    }
    mark_needs_human_review(request_id, report)
    return {"ok": True, "request_id": request_id, "status": "needs_human_review"}


async def _h_dev_clarify(args: dict, ctx: ToolContext):
    from community.core.dev_agent import DEV_ID as _DEV_ID, get_request
    if ctx.caller_agent_id != _DEV_ID:
        return {"ok": False, "reason": "only dev agent can call dev_clarify"}
    request_id = args.get("request_id")
    questions = args.get("questions") or []
    if not isinstance(request_id, int) or not questions:
        return {"ok": False, "reason": "request_id + questions[] required"}
    req = get_request(request_id)
    if not req:
        return {"ok": False, "reason": f"request #{request_id} not found"}
    return {"ok": True, "request_id": request_id, "questions_count": len(questions)}


# ── scene / tutorial ────────────────────────────────────────────────────────

async def _h_scene_advance(args: dict, ctx: ToolContext):
    from community.scenes import get_scene
    scene_id = args.get("scene_id", "").strip()
    phase = args.get("phase", "").strip()
    if not scene_id or not phase:
        return {"ok": False, "reason": "scene_id + phase 필수"}
    scene = get_scene(scene_id)
    if scene is None:
        return {"ok": False, "reason": f"unknown scene: {scene_id}"}

    if scene_id == "tutorial":
        if phase == "channels_setup":
            from community.scenes.tutorial.handlers import trigger_phase2
            await trigger_phase2(ctx.channels)
            return {"scene_id": scene_id, "phase": "channels_setup"}
        if phase == "complete":
            from community.scenes.tutorial.handlers import complete_tutorial
            await complete_tutorial()
            return {"scene_id": scene_id, "phase": "complete"}

    scene.set_phase(phase)
    from community.core.runtime import runtime
    try:
        runtime.refresh_agent(MGR_ID)
    except Exception:
        pass
    return {"scene_id": scene_id, "phase": phase}


async def _h_finish_profile_collection(args: dict, ctx: ToolContext):
    return await _h_scene_advance({"scene_id": "tutorial", "phase": "channels_setup"}, ctx)


async def _h_finish_tutorial(args: dict, ctx: ToolContext):
    try:
        personas = db.list_agents("persona")
    except Exception:
        personas = []
    if not personas:
        log_writer.system(
            "[finish_tutorial] 거부 — persona 0개. Hana 의 create_agent_profile 재확인."
        )
        return {
            "rejected": True, "reason": "no_persona_exists",
            "note": "튜토리얼 완료 조건 미달: persona 에이전트가 1개도 없음.",
        }
    return await _h_scene_advance({"scene_id": "tutorial", "phase": "complete"}, ctx)


# ── agent profile create/delete (delegate; create needs _cmd_profile_create) ─

async def _h_create_agent_profile(args: dict, ctx: ToolContext):
    # NOTE: _cmd_profile_create (에이전트 활성화 + dm 채널 + greet) 는 discord 본문이 길어
    # Phase 3 에선 미이식 — web 활성화 경로는 Phase 4 (boot/web_runtime) 에서 채널 어댑터로 연결.
    # 여기선 gender-lock / 중복 검증 + 이벤트 로그까지만 수행하고 활성화는 보류.
    import json as _j
    try:
        raw = args.get("args", "")
        payload = _j.loads(raw) if isinstance(raw, str) else raw
        new_name = (payload or {}).get("name")
    except Exception:
        payload, new_name = None, None
    if new_name:
        existing = db.get_agent_by_name(new_name)
        if existing and existing.get("type") == "persona":
            log_writer.system(f"[create_agent_profile] duplicate '{new_name}' — skip")
            return {"accepted": False, "reason": "already_exists",
                    "existing_id": existing["id"], "name": new_name}
    if isinstance(payload, dict):
        gender_raw = (payload.get("gender") or "").strip().lower()
        MALE_FORBIDDEN = {"남자", "male", "m", "남성"}
        FEMALE_OK = {"여자", "female", "f", "여성"}
        if gender_raw in MALE_FORBIDDEN:
            from glimi.tools.registry import env_truthy as _et
            imagegen_on = _et("GLIMI_IMAGEGEN")
            return {"accepted": False, "reason": "gender_locked_female_only_sample_path",
                    "imagegen_available": imagegen_on,
                    "note": "샘플 아바타가 여자만 준비됨."}
        if gender_raw not in FEMALE_OK:
            payload["gender"] = "여자"
            args["args"] = _j.dumps(payload, ensure_ascii=False)

    from community.core.profile_activation import activate_agent_from_json
    await activate_agent_from_json(args["args"], ctx)
    try:
        db.log_event("멤버합류", ["owner", new_name or "새친구"],
                     f"{new_name or '새친구'} 합류", impact="긍정")
    except Exception:
        pass
    return {"accepted": True}


async def _h_delete_agent_profile(args: dict, ctx: ToolContext):
    from community.core.profile_activation import deactivate_agent
    await deactivate_agent(args["name"], ctx)
    return {"name": args["name"]}


# ── profile image (imagegen) — adapter-routed reveal; avatar refresh no-op web ─

async def _h_set_profile_image(args: dict, ctx: ToolContext):
    from community.core.profile_image import apply_sample_profile_image
    from community.core.profile_preview import get_recent_preview, clear_preview
    requested = args["profile_image_filename"]
    channel_name = ctx.channel_name or ""
    previewed = get_recent_preview(ctx.caller_agent_id or "", channel_name)
    if previewed and previewed != requested:
        log_writer.system(f"[set_profile_image] preview mismatch — '{requested}' → '{previewed}'")
        requested = previewed
    target_agent = db.get_agent_by_name(args["name"])
    if target_agent and target_agent.get("sample_source_file") == requested:
        clear_preview(ctx.caller_agent_id or "", channel_name)
        return {"name": args["name"], "profile_image": requested, "skipped": True, "reason": "already_set"}
    await apply_sample_profile_image(args["name"], requested, ctx,
                                     caller_agent_id=ctx.caller_agent_id)
    clear_preview(ctx.caller_agent_id or "", channel_name)
    return {"name": args["name"], "profile_image": requested}


async def _h_generate_profile_image(args: dict, ctx: ToolContext):
    """LoRA portrait 생성 — 즉시 반환, 백그라운드가 ~6분 후 어댑터로 reveal."""
    import asyncio as _asyncio
    name = args["name"]
    character_block = args["character_block"]
    version = args.get("version", "v3") or "v3"
    target = db.get_agent_by_name(name)
    if not target:
        return {"ok": False, "error": f"agent not found: {name}"}
    agent_id = target["id"]
    caller_agent_id = ctx.caller_agent_id or "agent-creator-001"
    channel_name = ctx.channel_name
    channels = ctx.channels

    async def _bg():
        from community.core.profile_image import generate_for_agent
        try:
            result = await generate_for_agent(agent_id, character_block, version=version)
        except FileNotFoundError as e:
            log_writer.system(f"[generate_profile_image] LoRA missing: {e}")
            await channels.send_as_agent(channel_name, caller_agent_id,
                                         f"{name} 그리려는데 그림 도구 파일이 빠졌네 ㅠㅠ")
            return
        except Exception as e:
            log_writer.system(f"[generate_profile_image] error: {type(e).__name__}: {e}")
            await channels.send_as_agent(channel_name, caller_agent_id,
                                         f"{name} 그리다가 오류 났어 ㅠㅠ ({type(e).__name__})")
            return
        # webhook avatar 갱신 → web 에선 no-op (라이브 /api/avatar). discord 는 push.
        await channels.refresh_agent_avatar(agent_id)
        await channels.send_image_as_agent(
            channel_name, caller_agent_id, result["full_path"],
            caption=f"{name} 그렸어! 어때?",
        )

    _asyncio.create_task(_bg())
    return {"ok": True, "name": name, "agent_id": agent_id, "version": version,
            "status": "started", "estimated_seconds": 420,
            "note": "약 6-7분 후 자동으로 채널에 이미지가 올라가."}


async def _h_create_agent_with_image(args: dict, ctx: ToolContext):
    """신규 페르소나 + 직접 그린 이미지 deferred reveal (adapter-routed)."""
    import asyncio as _asyncio
    import json as _json
    raw_json = args["agent_json"]
    character_block = args["character_block"]
    yuna_message = (args.get("yuna_message") or "").strip()
    version = args.get("version", "v3") or "v3"
    try:
        payload = _json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except Exception as e:
        return {"ok": False, "error": f"agent_json JSON parse 실패: {e}"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "agent_json 은 object 여야 함"}
    name = payload.get("name")
    agent_id = payload.get("id")
    if not name or not agent_id:
        return {"ok": False, "error": "agent_json 에 id 와 name 필수"}
    existing = db.get_agent_by_name(name)
    if existing and existing.get("type") == "persona":
        return {"accepted": False, "reason": "already_exists", "existing_id": existing["id"], "name": name}
    if not (payload.get("gender") or "").strip():
        payload["gender"] = "여자"
    payload["profile_image_filename"] = f"{agent_id}.png"
    final_json_str = _json.dumps(payload, ensure_ascii=False)
    caller_agent_id = ctx.caller_agent_id or "agent-creator-001"
    channel_name = ctx.channel_name
    channels = ctx.channels

    async def _bg():
        from community.core.profile_image import generate_for_pending_agent
        from community.core.profile_activation import activate_agent_from_json
        from community.core.profile import invalidate_cache
        try:
            result = await generate_for_pending_agent(agent_id, character_block, version=version)
        except FileNotFoundError as e:
            log_writer.system(f"[create_agent_with_image] LoRA missing: {e}")
            await channels.send_as_agent(channel_name, caller_agent_id, f"{name} 그리려는데 도구 파일 빠짐 ㅠㅠ")
            return
        except Exception as e:
            log_writer.system(f"[create_agent_with_image] generation 실패: {type(e).__name__}: {e}")
            await channels.send_as_agent(channel_name, caller_agent_id, f"{name} 그리다 오류 ㅠㅠ ({type(e).__name__})")
            return
        try:
            await activate_agent_from_json(final_json_str, ctx)
        except Exception as e:
            log_writer.system(f"[create_agent_with_image] 활성화 실패: {type(e).__name__}: {e}")
            await channels.send_as_agent(channel_name, caller_agent_id, f"{name} 활성화 오류 ㅠㅠ ({type(e).__name__})")
            return
        invalidate_cache(agent_id)
        await channels.refresh_agent_avatar(agent_id)
        await channels.send_image_as_agent(channel_name, caller_agent_id, result["full_path"],
                                           caption=f"{name} 만들었어! 어때?")
        if yuna_message:
            try:
                from community.core.mgr_actions import forward_action
                yuna_payload = _json.dumps({"type": "DM", "target": "Yuna", "message": yuna_message}, ensure_ascii=False)
                await forward_action(caller_agent_id, yuna_payload, channels=channels)
            except Exception as e:
                log_writer.system(f"[create_agent_with_image] Yuna 보고 실패 (무시): {e}")
        try:
            db.log_event("멤버합류", ["owner", name], f"{name} 합류 (직접 그린 이미지)", impact="긍정")
        except Exception:
            pass

    _asyncio.create_task(_bg())
    return {"ok": True, "name": name, "agent_id": agent_id, "version": version,
            "status": "started", "estimated_seconds": 420,
            "note": "약 6-7분 후 이미지 생성 완료 → 활성화 + reveal."}


async def _h_approve_request(args: dict, ctx: ToolContext):
    # NOTE: yuna_approve_action 본문은 discord channel-create 가 많아 Phase 3 미이식.
    # web 승인 경로는 후속 — 여기선 결정만 기록.
    log_writer.system(
        f"[approve_request] #{args['request_id']} → {args['decision']} (web stub)"
    )
    return {"request_id": args["request_id"], "decision": args["decision"]}


# ── 조회 도구 (query — all DB-backed via mgr_actions.execute_yuna_query) ─────

async def _run_query(name: str, args_str: str, ctx: ToolContext) -> str:
    from community.core.mgr_actions import execute_yuna_query
    payload = f"{name} {args_str}".strip() if args_str else name
    return await execute_yuna_query(payload, channels=ctx.channels)


async def _h_list_channels(args, ctx):
    return {"result": await _run_query("채널목록", "", ctx)}


async def _h_list_members(args, ctx):
    return {"result": await _run_query("멤버목록", "", ctx)}


async def _h_get_logs(args, ctx):
    target = args["target"]
    since_min = args.get("since_minutes")
    from_time = args.get("from_time")
    to_time = args.get("to_time")
    limit = args.get("limit", 200)
    if since_min or from_time or to_time:
        from community import db as _db
        rows = _db.get_messages_in_range(
            channel=target, since=from_time or None, until=to_time or None,
            since_minutes=since_min, limit=int(limit) if limit else 200,
        )
        if not rows:
            return {"result": f"[{target}] 해당 범위 메시지 없음"}
        from community.core.profile import get_user_id, get_user_name
        from community.core.runtime import runtime as _rt
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
    from glimi.tools.reference import build_tool_details
    return {"result": build_tool_details(args["name"])}


async def _h_query_knowledge(args, ctx):
    from community import knowledge as _kb
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


async def _h_recall_memory(args: dict, ctx: ToolContext):
    from community.core.memory import recall_memory
    results = recall_memory(
        agent_id=ctx.caller_agent_id,
        query=args.get("query", "") or "",
        entity=args.get("entity", "") or "",
        time_range_days=args.get("time_range_days"),
        limit=int(args.get("limit") or 10),
    )
    return {"count": len(results), "results": results}


# ── 가수 페르소나 전용 query (file-backed, discord-free) ─────────────────────

def _load_agent_songs(agent_id: str) -> list[dict]:
    try:
        from community.community import get_community_dir
        path = get_community_dir() / "songs" / f"{agent_id}.json"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("songs") or []
    except Exception:
        return []


async def _h_get_my_songs(args: dict, ctx: ToolContext):
    songs = _load_agent_songs(ctx.caller_agent_id)
    if not songs:
        return {"result": "[조회결과] 등록된 곡 데이터 없음"}
    type_filter = (args.get("type") or "").strip().lower() or None
    q_filter = (args.get("q") or "").strip().lower()
    try:
        limit = max(1, min(int(args.get("limit") or 30), 200))
    except (TypeError, ValueError):
        limit = 30
    filtered = []
    for s in songs:
        if type_filter and s.get("type") != type_filter:
            continue
        if q_filter and q_filter not in (s.get("title") or "").lower():
            continue
        filtered.append(s)
    if not filtered:
        return {"result": "[조회결과] 조건 일치 곡 없음"}
    type_label = {"original": "오리", "collab": "콜라", "cover": "커버"}
    lines = [f"[내 곡 {len(filtered)}/{len(songs)}건]"]
    for s in filtered[:limit]:
        title = s.get("title", "?")
        date = s.get("date", "")
        tag = type_label.get(s.get("type"), "?")
        collab = f" w/ {s['collab_with']}" if s.get("collab_with") else ""
        mark = "♪" if s.get("lyrics") else ""
        lines.append(f"- [{tag}] {title} ({date}){collab} {mark}".rstrip())
    if len(filtered) > limit:
        lines.append(f"... 외 {len(filtered) - limit}건 (limit 초과)")
    lines.append("(♪ = 가사 등록됨, get_lyrics 로 조회 가능)")
    return {"result": "\n".join(lines)}


async def _h_get_lyrics(args: dict, ctx: ToolContext):
    title_q = (args.get("title") or "").strip()
    if not title_q:
        return {"result": "[조회결과] title 필요"}
    songs = _load_agent_songs(ctx.caller_agent_id)
    if not songs:
        return {"result": "[조회결과] 등록된 곡 데이터 없음"}
    target = next((s for s in songs if s.get("title") == title_q), None)
    if not target:
        ql = title_q.lower()
        candidates = [s for s in songs if ql in (s.get("title") or "").lower()]
        if not candidates:
            return {"result": f"[조회결과] '{title_q}' 일치 곡 없음"}
        if len(candidates) > 1:
            titles = ", ".join(s["title"] for s in candidates[:5])
            tail = "..." if len(candidates) > 5 else ""
            return {"result": f"[조회결과] '{title_q}' 후보 여러 개: {titles}{tail} — 더 명확히 지정"}
        target = candidates[0]
    title = target.get("title", "?")
    date = target.get("date", "")
    collab = target.get("collab_with")
    lyrics = target.get("lyrics")
    header = f"[{title} ({date})" + (f" — w/ {collab}" if collab else "") + "]"
    if lyrics is None or (isinstance(lyrics, str) and not lyrics.strip()):
        return {"result": f"{header}\n[가사 미등록] 임의 인용 금지."}
    return {"result": f"{header}\n{lyrics}"}


def _load_agent_concerts(agent_id: str) -> list[dict]:
    try:
        from community.community import get_community_dir
        path = get_community_dir() / "concerts" / f"{agent_id}.json"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("concerts") or []
    except Exception:
        return []


async def _h_get_my_concerts(args: dict, ctx: ToolContext):
    concerts = _load_agent_concerts(ctx.caller_agent_id)
    if not concerts:
        return {"result": "[조회결과] 등록된 콘서트 데이터 없음"}
    type_filter = (args.get("type") or "").strip().lower() or None
    q_filter = (args.get("q") or "").strip().lower()
    try:
        limit = max(1, min(int(args.get("limit") or 30), 100))
    except (TypeError, ValueError):
        limit = 30
    filtered = []
    for c in concerts:
        if type_filter and c.get("type") != type_filter:
            continue
        if q_filter:
            haystack = ((c.get("title") or "") + " " + (c.get("subtitle") or "")).lower()
            if q_filter not in haystack:
                continue
        filtered.append(c)
    if not filtered:
        return {"result": "[조회결과] 조건 일치 콘서트 없음"}
    type_label = {"youtube_3d": "3D", "live": "라이브"}
    lines = [f"[내 콘서트 {len(filtered)}/{len(concerts)}건]"]
    for c in filtered[:limit]:
        title = c.get("title", "?")
        subtitle = c.get("subtitle") or ""
        date = c.get("date", "")
        tag = type_label.get(c.get("type"), "?")
        n = len(c.get("setlist") or [])
        venue = f" @ {c['venue']}" if c.get("venue") else ""
        sub_str = f" — {subtitle}" if subtitle else ""
        lines.append(f"- [{tag}] {title}{sub_str} ({date}){venue} · {n}곡")
    if len(filtered) > limit:
        lines.append(f"... 외 {len(filtered) - limit}건 (limit 초과)")
    lines.append("(셋리스트는 get_concert_setlist 로 조회)")
    return {"result": "\n".join(lines)}


async def _h_get_concert_setlist(args: dict, ctx: ToolContext):
    title_q = (args.get("title") or "").strip()
    date_q = (args.get("date") or "").strip()
    if not title_q:
        return {"result": "[조회결과] title 필요"}
    concerts = _load_agent_concerts(ctx.caller_agent_id)
    if not concerts:
        return {"result": "[조회결과] 등록된 콘서트 데이터 없음"}
    pool = concerts
    if date_q:
        pool = [c for c in concerts if c.get("date") == date_q]
        if not pool:
            return {"result": f"[조회결과] date={date_q} 일치 콘서트 없음"}
    target = next((c for c in pool if c.get("title") == title_q), None)
    if not target:
        ql = title_q.lower()
        candidates = [c for c in pool if ql in (c.get("title") or "").lower()]
        if not candidates:
            return {"result": f"[조회결과] '{title_q}' 일치 콘서트 없음"}
        if len(candidates) > 1:
            opts = [f"{c['title']} ({c.get('date','?')}, {c.get('subtitle','')})" for c in candidates[:6]]
            tail = "..." if len(candidates) > 6 else ""
            return {"result": f"[조회결과] '{title_q}' 후보 여러 개:\n"
                    + "\n".join(f"  - {o}" for o in opts) + tail + "\ndate 파라미터로 더 좁히기"}
        target = candidates[0]
    title = target.get("title", "?")
    subtitle = target.get("subtitle") or ""
    date = target.get("date", "")
    venue = target.get("venue") or ""
    tour = target.get("tour") or ""
    sessions = target.get("session_members") or []
    setlist = target.get("setlist") or []
    notes = target.get("notes") or ""
    head_parts = [title]
    if subtitle:
        head_parts.append(f"({subtitle})")
    head = " ".join(head_parts) + f" — {date}"
    if venue:
        head += f" @ {venue}"
    lines = [f"[{head}]"]
    if tour:
        lines.append(f"투어: {tour}")
    if notes:
        lines.append(f"비고: {notes}")
    if sessions:
        lines.append(f"세션: {', '.join(sessions)}")
    lines.append(f"셋리스트 ({len(setlist)}곡):")
    for i, song in enumerate(setlist, 1):
        lines.append(f"  {i}. {song}")
    return {"result": "\n".join(lines)}


def _load_agent_lore(agent_id: str) -> list[dict]:
    try:
        from community.community import get_community_dir
        path = get_community_dir() / "lore" / f"{agent_id}.json"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("milestones") or []
    except Exception:
        return []


async def _h_get_my_history(args: dict, ctx: ToolContext):
    milestones = _load_agent_lore(ctx.caller_agent_id)
    if not milestones:
        return {"result": "[조회결과] 등록된 연혁 데이터 없음"}
    cat_filter = (args.get("category") or "").strip().lower() or None
    q_filter = (args.get("q") or "").strip().lower()
    try:
        limit = max(1, min(int(args.get("limit") or 30), 100))
    except (TypeError, ValueError):
        limit = 30
    filtered = []
    for m in milestones:
        if cat_filter and (m.get("category") or "").lower() != cat_filter:
            continue
        if q_filter:
            haystack = ((m.get("title") or "") + " " + (m.get("note") or "")).lower()
            if q_filter not in haystack:
                continue
        filtered.append(m)
    if not filtered:
        return {"result": "[조회결과] 조건 일치 연혁 없음"}
    filtered.sort(key=lambda m: m.get("date") or "")
    lines = [f"[내 연혁 {len(filtered)}/{len(milestones)}건]"]
    for m in filtered[:limit]:
        date = m.get("date", "?")
        cat = m.get("category", "?")
        title = m.get("title", "?")
        note = m.get("note") or ""
        line = f"- [{cat}] {date} {title}"
        if note:
            line += f" — {note}"
        lines.append(line)
    if len(filtered) > limit:
        lines.append(f"... 외 {len(filtered) - limit}건 (limit 초과)")
    return {"result": "\n".join(lines)}


async def _h_pin_memory(args: dict, ctx: ToolContext):
    from community.core.memory import pin_memory
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
    if result.get("ok") and result.get("agent_id") != a["id"]:
        pin_memory(memory_id, pinned=not pinned)
        raise ValueError(f"memory_id={memory_id}는 {name}의 기억이 아님 (owner={result.get('agent_id')})")
    return result


# ── 요청 도구 (persona → mgr) ───────────────────────────────────────────────

def _similar_prefix(a: str, b: str, threshold: float = 0.95) -> bool:
    if not a or not b:
        return False
    al = a[:60].lower().replace(" ", "")
    bl = b[:60].lower().replace(" ", "")
    if not al or not bl:
        return False
    shorter = min(len(al), len(bl))
    match = sum(1 for i in range(shorter) if al[i] == bl[i])
    return (match / shorter) >= threshold


async def _h_request_dm(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import forward_action
    target = args["target"]
    cur_msg = args.get("message", "") or ""
    try:
        caller_profile = db.get_agent(ctx.caller_agent_id) or {}
        caller_name = caller_profile.get("name", "")
    except Exception:
        caller_name = ""
    if caller_name and target.strip() == caller_name:
        log_writer.system(f"[request_dm] self-target 차단: {ctx.caller_agent_id}({caller_name}) → {target}")
        return {"rejected": True, "reason": "self_target", "target": target,
                "note": f"본인({caller_name}) 에게 request_dm 을 보낼 순 없음."}
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
    within_window = (now - prev_ts) < 180
    if within_window and prev_msg and _similar_prefix(prev_msg, cur_msg, threshold=0.80):
        log_writer.system(f"[request_dm] {ctx.caller_agent_id} → {target} 3분 내 유사 메시지 스킵")
        return {"skipped": True, "reason": "similar_message_within_3min", "target": target,
                "note": "최근 3분 내 비슷한 메시지를 이미 보냈다."}
    count_raw = db.get_meta(count_key) or ""
    try:
        count_obj = _json.loads(count_raw) if count_raw else {}
    except Exception:
        count_obj = {}
    timestamps = count_obj.get("ts_list", []) if isinstance(count_obj, dict) else []
    timestamps = [t for t in timestamps if (now - t) < 180]
    if len(timestamps) >= 3:
        log_writer.system(f"[request_dm] {ctx.caller_agent_id} → {target} 3분 내 {len(timestamps)}회 — 차단")
        return {"skipped": True, "reason": "too_frequent_same_target", "target": target,
                "note": f"{target}에게 3분 내 {len(timestamps)}번 보냄. 응답 기다려."}
    timestamps.append(now)
    db.set_meta(count_key, _json.dumps({"ts_list": timestamps}, ensure_ascii=False))
    db.set_meta(dedup_key, _json.dumps({"msg": cur_msg, "ts": now}, ensure_ascii=False))
    s = _json.dumps({"type": "DM", "target": target, "message": cur_msg}, ensure_ascii=False)
    await forward_action(ctx.caller_agent_id, s, channels=ctx.channels)
    try:
        db.log_event("dm_request", [ctx.caller_agent_id, target],
                     f"{ctx.caller_agent_id}가 {target}한테 DM 요청: {cur_msg[:60]}", impact="중립")
    except Exception:
        pass
    return {"forwarded_to": target}


async def _h_request_room(args: dict, ctx: ToolContext):
    from community.core.mgr_actions import forward_action
    s = json.dumps({"type": "톡방", "names": args.get("names", []),
                    "topic": args.get("topic", "")}, ensure_ascii=False)
    await forward_action(ctx.caller_agent_id, s, channels=ctx.channels)
    return {"names": args.get("names", []), "topic": args.get("topic", "")}


async def _h_bring_friend(args: dict, ctx: ToolContext):
    """페르소나가 자기 친구를 오너에게 소개 — Hana 에게 위임 (adapter-routed forward)."""
    from community.core.profile import get_user_id, get_user_name
    caller_id = ctx.caller_agent_id or ""
    caller = db.get_agent(caller_id) or {}
    if caller.get("type") != "persona":
        return {"ok": False, "reason": "only_persona", "note": "페르소나만 호출 가능"}
    friend_name = (args.get("friend_name") or "").strip()
    friend_concept = (args.get("friend_concept") or "").strip()
    rel_to_self = (args.get("relationship_to_self") or "").strip()
    rel_dynamics = (args.get("relationship_dynamics") or "").strip()
    if not friend_name or not friend_concept or not rel_to_self:
        return {"ok": False, "reason": "missing_fields"}
    owner_id = get_user_id() or "owner"
    rel = db.get_relationship(owner_id, caller_id) or db.get_relationship(caller_id, owner_id) or {}
    intimacy = rel.get("intimacy_score", 0)
    INTRO_THRESHOLD = 70
    if intimacy < INTRO_THRESHOLD:
        return {"ok": False, "reason": "intimacy_too_low", "current_intimacy": intimacy,
                "need": INTRO_THRESHOLD,
                "note": f"오너랑 친밀도가 70 이상이어야 친구 데려오기 가능 (현재 {intimacy}/{INTRO_THRESHOLD})"}
    try:
        conn = db.get_conn()
        recent = conn.execute(
            "SELECT id FROM events WHERE event_type='친구소개_제안' "
            "AND participants LIKE ? AND timestamp >= datetime('now', '-24 hours') LIMIT 1",
            (f"%{caller_id}%",),
        ).fetchone()
        conn.close()
        if recent:
            return {"ok": False, "reason": "cooldown", "note": "최근 24시간 내 이미 친구 데려오기 시도."}
    except Exception:
        pass
    caller_name = caller.get("name", "?")
    owner_name = get_user_name() or "오너"
    try:
        db.log_event("친구소개_제안", [caller_id, owner_id],
                     f"{caller_name} 가 자기 친구 {friend_name} 을 {owner_name} 에게 소개 제안 ({rel_to_self})",
                     impact="마일스톤")
    except Exception:
        pass
    relay_msg = (
        f"[친구 소개 위임 — {caller_name} ({caller_id}) 발의]\n"
        f"오너({owner_name})랑 친한 {caller_name} 가 자기 친구 {friend_name} 데려오겠다고 함.\n\n"
        f"새 친구 정보:\n  - 이름: {friend_name}\n  - 컨셉: {friend_concept}\n"
        f"  - {caller_name} 와의 관계: {rel_to_self} (intimacy 75)"
        f"{' — ' + rel_dynamics if rel_dynamics else ''}\n"
        f"  - 오너와의 관계: 초면 (intimacy 30, '{caller_name} 통해 알게 됨')\n\n"
        f"create_agent_profile 호출 시 relationship_templates 에 다음 포함:\n"
        f'  {{"target_id": "{caller_id}", "rel_type": "{rel_to_self}", '
        f'"intimacy": 75, "dynamics": "{rel_dynamics or rel_to_self}", "is_owner_relationship": 0}}\n\n'
        f"오너 확인 후 진행."
    )
    try:
        from community.core.mgr_actions import forward_action
        import json as _json
        action_payload = _json.dumps({"type": "REQUEST_DM", "target": "윤하나", "message": relay_msg}, ensure_ascii=False)
        await forward_action(caller_id, action_payload, channels=ctx.channels)
    except Exception as e:
        log_writer.system(f"[bring_friend] forward 실패: {type(e).__name__}: {e}")
    log_writer.system(f"[bring_friend] {caller_name}({caller_id}) → 친구 {friend_name} 소개 제안 (intimacy {intimacy})")
    return {"ok": True, "proposed_friend": friend_name, "delegated_to": "윤하나",
            "caller_intimacy": intimacy,
            "note": "Hana 가 처리 시작 — 오너 컨펌 후 생성됨."}


# ── 레지스트리 주입 ──────────────────────────────────────────────────────────

_MAP = {
    # management
    "create_room": _h_create_room,
    "start_conversation": _h_start_conversation,
    "stop_conversation": _h_stop_conversation,
    "delete_channel": _h_delete_channel,
    "rename_channel": _h_rename_channel,
    "set_topic": _h_set_topic,
    "purge_messages": _h_purge_messages,
    "set_emotion": _h_set_emotion,
    "update_profile": _h_update_profile,
    "update_relationship": _h_update_relationship,
    "invoke_agent": _h_invoke_agent,
    "reset_channel": _h_reset_channel,
    "clear_messages": _h_clear_messages,
    "reset_agent": _h_reset_agent,
    "revive_persona": _h_revive_persona,
    "request_dev_task": _h_request_dev_task,
    "request_dev_fix": _h_request_dev_fix,
    "dev_organize": _h_dev_organize,
    "dev_escalate": _h_dev_escalate,
    "dev_clarify": _h_dev_clarify,
    "scene_advance": _h_scene_advance,
    "finish_profile_collection": _h_finish_profile_collection,
    "finish_tutorial": _h_finish_tutorial,
    "create_agent_profile": _h_create_agent_profile,
    "delete_agent_profile": _h_delete_agent_profile,
    "set_profile_image": _h_set_profile_image,
    "generate_profile_image": _h_generate_profile_image,
    "create_agent_with_image": _h_create_agent_with_image,
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
    "recall_memory": _h_recall_memory,
    # 가수 페르소나 전용 query
    "get_my_songs": _h_get_my_songs,
    "get_lyrics": _h_get_lyrics,
    "get_my_concerts": _h_get_my_concerts,
    "get_concert_setlist": _h_get_concert_setlist,
    "get_my_history": _h_get_my_history,
    # request
    "request_dm": _h_request_dm,
    "request_room": _h_request_room,
    "bring_friend": _h_bring_friend,
}


def register_all():
    """registry에 모든 핸들러 주입. 런타임 부팅 시 1회 호출."""
    for name, fn in _MAP.items():
        set_handler(name, fn)
