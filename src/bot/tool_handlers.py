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
from src.glimi.tools.registry import set_handler
from src.glimi.tools.dispatcher import ToolContext


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
    from src.bot.conversation_bridge import stop_conversation, list_active_conversations
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
    from src.core.emotion_emoji import register_emoji_for
    # emoji 가 같이 들어오면 community-local emotion→emoji 매핑에 등록 (idempotent — 첫 등록만)
    emoji = (args.get("emoji") or "").strip()
    emotion = (args.get("emotion") or "").strip()
    if emoji and emotion:
        try:
            register_emoji_for(emotion, emoji)
        except Exception:
            pass
    s = f"{args['name']} {emotion} {args['intensity']}"
    await yuna_change_emotion(ctx.channel_obj, s)
    return {"name": args["name"], "emotion": emotion, "intensity": args["intensity"], "emoji": emoji}


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


async def _h_request_dev_fix(args: dict, ctx: ToolContext):
    """매니저 (유나/하나) 또는 오너가 호출 — dev_requests 큐에 적재 + dev 봇 lazy seed.

    args: {channel, severity ('low'|'med'|'high'), repro, expected, actual, notes?}

    동작 흐름:
      1. payload 검증
      2. **dedup 체크** — 같은 community + 같은 channel + 같은 severity 의 pending/analyzed
         가 60분 안에 있으면 거절하고 기존 request_id 알려줌 (회귀 방지: 매니저가 같은 버그
         반복 보고하는 경우)
      3. mgr-dev-request 채널 ensure
      4. dev_requests INSERT
      5. **mgr-dev-request 채널에 caller 명의로 보고 한 줄 post** (1인극 해소)
      6. dev agent lazy seed + runtime invalidate
    """
    from src.core.dev_agent import (
        ensure_dev_seeded, enqueue_dev_request, find_similar_recent_request,
        DEV_CHANNEL, DEV_ID,
    )
    from src import community as _community

    # 페이로드 검증
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

    # ── dedup gate ──────────────────────────────────────────
    # 같은 채널·같은 severity 의 pending/analyzed 가 60분 안에 있으면 새로 만들지 않음.
    # 이미 큐에 들어가 있는 동일 이슈를 중복 보고하는 회귀 (2026-04-30 유나 7회 동일 보고) 차단.
    existing = find_similar_recent_request(community_id, payload, window_minutes=60)
    if existing:
        log_writer.system(
            f"[dev] dedup hit — 기존 #{existing['id']} 와 같은 channel/severity, 새 요청 거절"
        )
        return {
            "ok": False,
            "reason": "duplicate_recent_request",
            "existing_request_id": existing["id"],
            "existing_status": existing["status"],
            "hint": "같은 채널·심각도의 최근 요청이 이미 큐에 있어. 추가 정보 있으면 그 요청에 코멘트로 붙이거나 시간 두고 다시 봐.",
        }

    # Lazy seed dev agent (community-local 시드 — agent 자체는 community DB 에 살음)
    seeded_now = ensure_dev_seeded()

    # mgr-dev-request 채널 ensure (Discord 어댑터 — guild 객체 필요).
    dev_channel_obj = None
    if ctx.guild is not None:
        try:
            from src.core.sync import ensure_unique_channel
            from src.bot.core import _ensure_category
            from src.bot import MGR_ID
            category = await _ensure_category(ctx.guild, "glimi-mgr")
            dev_channel_obj, _created = await ensure_unique_channel(ctx.guild, DEV_CHANNEL, category)
            db.set_channel_participants(DEV_CHANNEL, [DEV_ID, MGR_ID])
        except Exception as e:
            log_writer.system(f"[dev] ⚠ {DEV_CHANNEL} 채널 ensure 실패: {type(e).__name__}: {e}")

    request_id = enqueue_dev_request(community_id, requested_by, payload)

    # ── caller 명의로 mgr-dev-request 채널에 보고 한 줄 post ──
    # 이전엔 INSERT 만 하고 채널엔 아무 발화 없음 → 세나만 일방적으로 분석 떠드는 1인극.
    # 채널 컨텍스트에 보고 자체가 보여야 세나의 분석이 맥락 안에서 읽힘.
    if dev_channel_obj is not None and requested_by != "owner":
        try:
            from src.bot.core import send_as_agent
            sev_label = {"low": "낮음", "med": "보통", "high": "높음"}.get(payload["severity"], payload["severity"])
            short_repro = payload["repro"][:80] + ("…" if len(payload["repro"]) > 80 else "")
            short_actual = payload["actual"][:80] + ("…" if len(payload["actual"]) > 80 else "")
            report_msg = (
                f"[버그 #{request_id}] {sev_label} · #{payload['channel']}\n"
                f"증상: {short_repro}\n"
                f"실제: {short_actual}"
            )
            await send_as_agent(dev_channel_obj, requested_by, report_msg, paced=False)
        except Exception as e:
            log_writer.system(f"[dev] ⚠ 보고 post 실패 (#{request_id}): {type(e).__name__}: {e}")

    # runtime cache invalidate — dev agent 가 이번 요청 받아서 처리하도록
    if seeded_now:
        try:
            from src.core import runtime as _rt
            if hasattr(_rt, "invalidate_cache"):
                _rt.invalidate_cache(DEV_ID)
        except Exception:
            pass

    return {
        "ok": True,
        "request_id": request_id,
        "community_id": community_id,
        "dispatched_to": "한세나",
        "channel": DEV_CHANNEL,
    }


async def _h_dev_organize(args: dict, ctx: ToolContext):
    """Dev 봇 (세나) 전용 — pending 요청을 분석해서 admin 검토 대기 (analyzed) 로 전환.

    args: {request_id, task_brief, files_hint?, analysis_notes, sera_summary, confidence}
        confidence: 'high' | 'low' — admin 가 우선순위 정할 때 시그널.
        세나가 직접 코드 수정 X — 정리만 함. 실제 dispatch 는 admin 이 별도 페이지에서 트리거.

    files_hint 안전장치 (2026-04-30 회귀 방지):
      세나가 코드베이스 안 보고 환각 경로 (`src/core/dispatch.py` 등 실존 X) 를 적는 회귀.
      각 경로를 PROJECT_ROOT 기준으로 존재 검증 → 없는 건 strip + analysis_notes 에 기록.
      모든 경로가 환각이면 confidence=low 강제 + escalate 권고.
    """
    from src.core.dev_agent import DEV_ID, get_request, mark_analyzed
    from pathlib import Path as _Path

    if ctx.caller_agent_id != DEV_ID:
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

    # ── files_hint 환각 검증 ──────────────────────────────
    project_root = _Path(__file__).resolve().parent.parent.parent  # src/bot/X.py → glimi/
    real_files: list[str] = []
    hallucinated: list[str] = []
    for p in files_hint:
        if not isinstance(p, str) or not p.strip():
            continue
        rel = p.strip().lstrip("./")
        # 절대 경로면 거절 (보안 + 사고 예방)
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
            f"{', '.join(hallucinated)}. 세나가 추측한 환각 경로일 가능성 높음. "
            f"admin 검토 시 실제 코드베이스 grep 필수."
        )
        log_writer.system(
            f"[dev] #{request_id} files_hint 환각 {len(hallucinated)}건 strip "
            f"(real={len(real_files)}, hallucinated={hallucinated})"
        )

    # 모든 경로가 환각 → confidence=low 강제 (admin 한테 신호)
    if files_hint and not real_files:
        confidence = "low"
        extra_notes += (
            "\n[validator] 모든 files_hint 경로가 환각 — confidence 강제 down. "
            "admin 이 직접 코드베이스 검색 후 진행 권장."
        )

    final_notes = (analysis_notes + extra_notes).strip()
    mark_analyzed(request_id, task_brief, real_files, final_notes, sera_summary, confidence)
    return {
        "ok": True,
        "request_id": request_id,
        "status": "analyzed",
        "confidence": confidence,
        "files_hint_real": real_files,
        "files_hint_hallucinated": hallucinated,
    }


async def _h_dev_escalate(args: dict, ctx: ToolContext):
    """Dev 봇만 호출 — 정리도 안 되는 모호한 케이스를 직접 admin 검토로 (analyzed 건너뜀).

    args: {request_id, summary, decision_points[], suggested_options?[], context_files?[], severity}
    """
    from src.core.dev_agent import DEV_ID, get_request, mark_needs_human_review

    if ctx.caller_agent_id != DEV_ID:
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
        "summary": summary,
        "decision_points": decision_points,
        "suggested_options": args.get("suggested_options") or [],
        "context_files": args.get("context_files") or [],
        "severity": args.get("severity", "med"),
    }
    mark_needs_human_review(request_id, report)
    return {"ok": True, "request_id": request_id, "status": "needs_human_review"}


async def _h_dev_clarify(args: dict, ctx: ToolContext):
    """Dev 봇만 호출 — 요청 페이로드가 모호할 때 보고자에게 질문.

    args: {request_id, questions[]}
    질문은 mgr-dev-request 채널에 게시되어 보고자(유나/하나) 가 추가 메시지로 응답.
    status 는 pending 유지 → 답변 받으면 다음 턴에 다시 분석.
    """
    from src.core.dev_agent import DEV_ID, get_request

    if ctx.caller_agent_id != DEV_ID:
        return {"ok": False, "reason": "only dev agent can call dev_clarify"}

    request_id = args.get("request_id")
    questions = args.get("questions") or []
    if not isinstance(request_id, int) or not questions:
        return {"ok": False, "reason": "request_id + questions[] required"}

    req = get_request(request_id)
    if not req:
        return {"ok": False, "reason": f"request #{request_id} not found"}

    return {"ok": True, "request_id": request_id, "questions_count": len(questions)}


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
            return {"accepted": False, "reason": "already_exists",
                    "existing_id": existing["id"], "name": new_name}

    # Gender lock — 샘플 아바타 뱅크 여자만 준비 (sample 경로 한정).
    # 남자 캐릭터는 imagegen 활성 (`./run.sh --imagegen`) 시 `create_agent_with_image`
    # 로만 가능. 이 도구 (`create_agent_profile`) 는 sample 사용이라 여전히 여자 lock.
    if isinstance(payload, dict):
        gender_raw = (payload.get("gender") or "").strip().lower()
        FEMALE_OK = {"여자", "female", "f", "여성"}
        MALE_FORBIDDEN = {"남자", "male", "m", "남성"}
        if gender_raw in MALE_FORBIDDEN:
            from src.glimi.tools.registry import _env_truthy as _et
            imagegen_on = _et("GLIMI_IMAGEGEN")
            log_writer.system(
                f"[create_agent_profile] gender='{gender_raw}' rejected — sample path is female-only "
                f"(imagegen={imagegen_on})"
            )
            note = (
                "샘플 아바타가 여자만 준비됨. "
                + ("**남자 만들고 싶으면 `create_agent_with_image` 도구 사용** "
                   "(직접 그리기 — 6-7분 소요). 오너에게 '남자는 직접 그려야 해서 좀 걸려, 괜찮아?' 안내."
                   if imagegen_on else
                   "오너에게 '남자 캐릭터는 임시로 어려워서 여자로 만들게' 식 redirect 필요.")
            )
            return {
                "accepted": False, "reason": "gender_locked_female_only_sample_path",
                "imagegen_available": imagegen_on,
                "note": note,
            }
        if gender_raw not in FEMALE_OK:
            # 명시 없거나 모호하면 자동으로 '여자' 채워서 진행
            payload["gender"] = "여자"
            args["args"] = _j.dumps(payload, ensure_ascii=False)
            log_writer.system(
                f"[create_agent_profile] gender 자동 보정 → '여자' (was '{gender_raw or 'empty'}')"
            )

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


async def _h_generate_profile_image(args: dict, ctx: ToolContext):
    """LoRA portrait 직접 생성 — 즉시 반환, 백그라운드 task 가 ~6-7분 후 채널에 이미지 게시.

    flow:
        1) 동기 처리: 대상 agent 존재 확인 → "started" payload 반환 (LLM 에 곧바로 응답)
        2) 비동기 task: generate_for_agent (executor 에서 ~6분) → webhook avatar 갱신 →
           caller 에이전트로 채널에 이미지 + 한마디
    """
    import asyncio as _asyncio

    name = args["name"]
    character_block = args["character_block"]
    version = args.get("version", "v3") or "v3"

    target = db.get_agent_by_name(name)
    if not target:
        return {"ok": False, "error": f"agent not found: {name}"}
    agent_id = target["id"]

    # caller / channel / guild 캡처 — task 안에서 ctx 직접 참조 시 stale 가능성
    caller_agent_id = ctx.caller_agent_id or "agent-creator-001"
    channel_obj = ctx.channel_obj
    guild = ctx.guild

    async def _bg():
        from src.core.profile_image import generate_for_agent
        from src.bot.core import (
            send_as_agent, send_image_as_agent, update_agent_webhook_profile_image,
        )
        try:
            result = await generate_for_agent(agent_id, character_block, version=version)
        except FileNotFoundError as e:
            log_writer.system(f"[generate_profile_image] LoRA missing: {e}")
            await send_as_agent(
                channel_obj, caller_agent_id,
                f"{name} 그리려는데 그림 도구 파일이 빠졌네 ㅠㅠ 세나한테 알려야겠다",
            )
            return
        except Exception as e:
            log_writer.system(f"[generate_profile_image] error: {type(e).__name__}: {e}")
            await send_as_agent(
                channel_obj, caller_agent_id,
                f"{name} 그리다가 오류 났어 ㅠㅠ ({type(e).__name__})",
            )
            return

        # webhook avatar 즉시 갱신 — set_profile_image 와 동일 패턴
        if guild is not None:
            updated = 0
            for ch in guild.text_channels:
                try:
                    whs = await ch.webhooks()
                    if any(wh.name == f"glimi-{agent_id}" for wh in whs):
                        if await update_agent_webhook_profile_image(ch, agent_id):
                            updated += 1
                except Exception:
                    pass
            log_writer.system(f"[generate_profile_image] webhook avatar 갱신: {updated}개")

        # 채널에 완료 통지 + 이미지 (full 버전 — 드러내기 좋게 832×1216).
        # crop 은 silently 에이전트 webhook avatar 로 적용 완료.
        await send_image_as_agent(
            channel_obj, caller_agent_id,
            result["full_path"],
            caption=f"{name} 그렸어! 어때?",
        )

    _asyncio.create_task(_bg())
    return {
        "ok": True,
        "name": name,
        "agent_id": agent_id,
        "version": version,
        "status": "started",
        "estimated_seconds": 420,
        "note": "약 6-7분 후 자동으로 채널에 이미지가 올라가. 그동안 다른 일 하면 됨.",
    }


async def _h_create_agent_with_image(args: dict, ctx: ToolContext):
    """신규 페르소나 + 직접 그린 이미지 deferred reveal — 단일 도구 (Path B).

    flow:
        1) 동기: agent_json 검증 (gender lock / duplicate / id format) → "started" 반환
        2) 비동기 task:
           a. generate_for_pending_agent (~6분) — 파일만 저장, DB UPDATE 없음
           b. _cmd_profile_create — 에이전트 활성화 + dm 채널 + greet
           c. profile_image_filename UPDATE + cache invalidate
           d. 모든 채널 webhook avatar 갱신
           e. mgr-creator 에 reveal: full 이미지 + caption '{name} 만들었어! 어때?'
           f. yuna_message 가 있으면 _forward_action_to_yuna 로 자동 보고
    """
    import asyncio as _asyncio
    import json as _json

    raw_json = args["agent_json"]
    character_block = args["character_block"]
    yuna_message = (args.get("yuna_message") or "").strip()
    version = args.get("version", "v3") or "v3"

    # ── JSON 파싱 + 사전 검증 ──────────────────────
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

    # 중복 검사
    existing = db.get_agent_by_name(name)
    if existing and existing.get("type") == "persona":
        log_writer.system(
            f"[create_agent_with_image] duplicate '{name}' — skip (existing id={existing['id']})"
        )
        return {"accepted": False, "reason": "already_exists",
                "existing_id": existing["id"], "name": name}

    # Gender — 직접 생성 경로는 imagegen ON 일 때만 호출 가능 (requires_env 게이트). LoRA 가
    # 영어 prompt 의 "korean female / male" 스왑으로 양쪽 그릴 수 있으므로 lock 없음.
    # 남자 sample 미배포라 sample 경로 (`_h_create_agent_profile`) 만 여자 제한 유지.
    gender_raw = (payload.get("gender") or "").strip()
    if not gender_raw:
        payload["gender"] = "여자"  # default — 명시 없으면 여자
        log_writer.system(
            "[create_agent_with_image] gender 비어있어 default '여자'"
        )

    # profile_image_filename 자동 셋업 (LoRA 출력 file 명과 일치)
    payload["profile_image_filename"] = f"{agent_id}.png"
    final_json_str = _json.dumps(payload, ensure_ascii=False)

    # 캡쳐 (task 내부에서 ctx 직접 참조 시 stale 가능성)
    caller_agent_id = ctx.caller_agent_id or "agent-creator-001"
    channel_obj = ctx.channel_obj
    guild = ctx.guild

    async def _bg():
        from src.core.profile_image import generate_for_pending_agent
        from src.bot.mgr_system import _cmd_profile_create, _forward_action_to_yuna
        from src.bot.core import (
            send_as_agent, send_image_as_agent, update_agent_webhook_profile_image,
        )
        from src.core.profile import invalidate_cache

        # ── 1) 이미지 생성 (DB 갱신 없이 파일만) ─────────
        try:
            result = await generate_for_pending_agent(agent_id, character_block, version=version)
        except FileNotFoundError as e:
            log_writer.system(f"[create_agent_with_image] LoRA missing: {e}")
            await send_as_agent(channel_obj, caller_agent_id,
                                f"{name} 그리려는데 그림 도구 파일이 빠졌네 ㅠㅠ 세나한테 알려야겠다")
            return
        except Exception as e:
            log_writer.system(
                f"[create_agent_with_image] generation 실패: {type(e).__name__}: {e}"
            )
            await send_as_agent(channel_obj, caller_agent_id,
                                f"{name} 그리다가 오류 났어 ㅠㅠ ({type(e).__name__})")
            return

        # ── 2) 에이전트 활성화 (DB insert + relationships + dm 채널 + greet) ──
        # _cmd_profile_create 가 profile_image_filename 도 보존 (payload 에 셋업해뒀음).
        try:
            await _cmd_profile_create(channel_obj, final_json_str)
        except Exception as e:
            log_writer.system(
                f"[create_agent_with_image] _cmd_profile_create 실패: {type(e).__name__}: {e}"
            )
            await send_as_agent(channel_obj, caller_agent_id,
                                f"{name} 활성화 단계에서 오류 ㅠㅠ ({type(e).__name__})")
            return

        # ── 3) 이미지 적용 확실히 (cache invalidate) ─────
        invalidate_cache(agent_id)

        # ── 4) 모든 채널의 webhook avatar 갱신 ─────────
        if guild is not None:
            updated = 0
            for ch in guild.text_channels:
                try:
                    whs = await ch.webhooks()
                    if any(wh.name == f"glimi-{agent_id}" for wh in whs):
                        if await update_agent_webhook_profile_image(ch, agent_id):
                            updated += 1
                except Exception:
                    pass
            log_writer.system(f"[create_agent_with_image] webhook avatar 갱신: {updated}개")

        # ── 5) mgr-creator 에 reveal (full 이미지) ─────
        await send_image_as_agent(
            channel_obj, caller_agent_id,
            result["full_path"],
            caption=f"{name} 만들었어! 어때?",
        )

        # ── 6) Yuna 자동 보고 (yuna_message 있으면) ─────
        if yuna_message:
            try:
                yuna_payload = _json.dumps(
                    {"type": "DM", "target": "Yuna", "message": yuna_message},
                    ensure_ascii=False,
                )
                await _forward_action_to_yuna(caller_agent_id, yuna_payload, guild)
                log_writer.system(
                    f"[create_agent_with_image] Yuna 보고: {yuna_message[:60]}"
                )
            except Exception as e:
                log_writer.system(
                    f"[create_agent_with_image] Yuna 보고 실패 (무시): {e}"
                )

        # ── 7) 멤버합류 이벤트 ───────────────────────
        try:
            db.log_event("멤버합류", ["owner", name],
                         f"{name} 합류 (직접 그린 이미지, MBTI: {payload.get('mbti', '?')}, "
                         f"관계: {(payload.get('relationship_to_owner') or {}).get('type', '?')})",
                         impact="긍정")
        except Exception:
            pass

    _asyncio.create_task(_bg())
    return {
        "ok": True,
        "name": name,
        "agent_id": agent_id,
        "version": version,
        "status": "started",
        "estimated_seconds": 420,
        "note": (
            "약 6-7분 후 이미지 생성 완료 → 에이전트 자동 활성화 + dm 채널 생성 + "
            "mgr-creator 에 이미지 reveal + Yuna 보고. 그동안 추가 호출/재촉 금지."
        ),
    }


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
    from src.glimi.tools.reference import build_tool_details
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

async def _h_bring_friend(args: dict, ctx: ToolContext):
    """페르소나가 자기 다른 친구를 오너에게 소개하고 싶을 때.

    동작 흐름:
      1) 호출자 페르소나 검증 + 오너와 intimacy ≥ 70 확인
      2) Hana 한테 internal-dm 보내서 새 친구 생성 위임 — 친구의 컨셉 + 호출자와의 관계
         dynamics 미리 채워서 Hana 가 create_agent_profile 시 relationship_templates 에
         자동으로 시드.
      3) 새 친구는 호출자와 절친 (75) + 오너와 초면 (30) 으로 시작.
      4) events 테이블에 기록 (대시보드 가시화).
    """
    from src.bot.mgr_system import _forward_action_to_yuna
    from src.core.profile import get_user_id, get_user_name

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

    # 친밀도 체크
    owner_id = get_user_id() or "owner"
    rel = db.get_relationship(owner_id, caller_id) or db.get_relationship(caller_id, owner_id) or {}
    intimacy = rel.get("intimacy_score", 0)
    INTRO_THRESHOLD = 70
    if intimacy < INTRO_THRESHOLD:
        return {
            "ok": False,
            "reason": "intimacy_too_low",
            "current_intimacy": intimacy,
            "need": INTRO_THRESHOLD,
            "note": "오너랑 친밀도가 70 이상이어야 친구 데려오기 가능 (현재 {}/{})".format(intimacy, INTRO_THRESHOLD),
        }

    # 중복 방지 — 같은 caller 가 24시간 내 이미 친구 데려오기 발의했으면 차단
    try:
        conn = db.get_conn()
        recent = conn.execute(
            "SELECT id FROM events WHERE event_type='친구소개_제안' "
            "AND participants LIKE ? "
            "AND timestamp >= datetime('now', '-24 hours') LIMIT 1",
            (f"%{caller_id}%",),
        ).fetchone()
        conn.close()
        if recent:
            return {
                "ok": False,
                "reason": "cooldown",
                "note": "최근 24시간 내 이미 친구 데려오기 시도 — 너무 자주 발의하면 부자연스러움",
            }
    except Exception:
        pass

    caller_name = caller.get("name", "?")
    owner_name = get_user_name() or "오너"

    # 이벤트 기록 (대시보드 가시화)
    try:
        db.log_event(
            "친구소개_제안",
            [caller_id, owner_id],
            f"{caller_name} 가 자기 친구 {friend_name} 을 {owner_name} 에게 소개 제안 ({rel_to_self})",
            impact="마일스톤",
        )
    except Exception:
        pass

    # Hana 에게 internal-dm 으로 위임 — 컨셉 + 관계 미리 박혀 있어서 Hana 가 그대로 create_agent_profile
    relay_msg = (
        f"[친구 소개 위임 — {caller_name} ({caller_id}) 발의]\n"
        f"오너({owner_name})랑 친한 {caller_name} 가 자기 친구 {friend_name} 데려오겠다고 함.\n\n"
        f"새 친구 정보:\n"
        f"  - 이름: {friend_name}\n"
        f"  - 컨셉: {friend_concept}\n"
        f"  - {caller_name} 와의 관계: {rel_to_self} (intimacy 75)"
        f"{' — ' + rel_dynamics if rel_dynamics else ''}\n"
        f"  - 오너와의 관계: 초면 (intimacy 30, '{caller_name} 통해 알게 됨')\n\n"
        f"create_agent_profile 호출 시 relationship_templates 에 다음 항목 포함:\n"
        f'  {{"target_id": "{caller_id}", "rel_type": "{rel_to_self}", '
        f'"intimacy": 75, "dynamics": "{rel_dynamics or rel_to_self}", "is_owner_relationship": 0}}\n\n'
        f"오너 확인 후 진행 — 오너가 거부하면 \"빈이가 아직 부담스럽대\" 식으로 자연스럽게 거절."
    )
    try:
        # request_dm 호출 흐름과 동일 — Yuna 가 받아 처리, internal-dm 통해 Hana 와 협의
        from src.bot.mgr_system import _forward_action_to_yuna as _fwd
        import json as _json
        action_payload = _json.dumps({
            "type": "REQUEST_DM",
            "target": "윤하나",
            "message": relay_msg,
        }, ensure_ascii=False)
        await _fwd(caller_id, action_payload, ctx.guild)
    except Exception as e:
        log_writer.system(f"[bring_friend] forward 실패: {type(e).__name__}: {e}")

    log_writer.system(
        f"[bring_friend] {caller_name}({caller_id}) → 친구 {friend_name} 소개 제안 (intimacy {intimacy})"
    )
    return {
        "ok": True,
        "proposed_friend": friend_name,
        "delegated_to": "윤하나",
        "caller_intimacy": intimacy,
        "note": "Hana 가 처리 시작 — 오너 컨펌 후 생성됨. 새 친구는 너랑 절친 75, 오너랑 초면 30 으로 시작.",
    }


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


# ── 가수 페르소나 전용 — 디스코그래피/가사/콘서트/연혁 ──────────────

def _load_agent_songs(agent_id: str) -> list[dict]:
    """`{community}/songs/{agent_id}.json` 로드. 파일 없으면 [] 반환."""
    try:
        from src.community import get_community_dir
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

    # 1) 정확매치
    target = next((s for s in songs if s.get("title") == title_q), None)
    if not target:
        # 2) 부분매치 (대소문자 무시)
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
        return {
            "result": (
                f"{header}\n[가사 미등록] 이 곡 가사 데이터는 아직 저장되어 있지 않음. "
                f"학습 메모리에서 임의로 끌어와 인용하지 말 것 — 모른다고 답하거나 곡 분위기·발매 시점 정도만 자연스럽게 얘기하기."
            )
        }

    return {"result": f"{header}\n{lyrics}"}


def _load_agent_concerts(agent_id: str) -> list[dict]:
    """`{community}/concerts/{agent_id}.json` 로드. 파일 없으면 [] 반환."""
    try:
        from src.community import get_community_dir
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

    # 1) date 가 있으면 우선 좁히기
    pool = concerts
    if date_q:
        pool = [c for c in concerts if c.get("date") == date_q]
        if not pool:
            return {"result": f"[조회결과] date={date_q} 일치 콘서트 없음"}

    # 2) 정확매치
    target = next((c for c in pool if c.get("title") == title_q), None)
    if not target:
        ql = title_q.lower()
        candidates = [c for c in pool if ql in (c.get("title") or "").lower()]
        if not candidates:
            return {"result": f"[조회결과] '{title_q}' 일치 콘서트 없음"}
        if len(candidates) > 1:
            opts = [f"{c['title']} ({c.get('date','?')}, {c.get('subtitle','')})" for c in candidates[:6]]
            tail = "..." if len(candidates) > 6 else ""
            return {
                "result": (
                    f"[조회결과] '{title_q}' 후보 여러 개:\n"
                    + "\n".join(f"  - {o}" for o in opts)
                    + tail
                    + "\ndate 파라미터로 더 좁히기"
                )
            }
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
    """`{community}/lore/{agent_id}.json` 로드. 파일 없으면 [] 반환."""
    try:
        from src.community import get_community_dir
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

    # 날짜 오름차순으로 정렬 — 시간순 흐름이 자연스러움
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
    "request_dev_task": _h_request_dev_task,        # 레거시 — 봇 종료 후 외부 dev 워크플로우
    "request_dev_fix": _h_request_dev_fix,          # mgr/creator/owner — dev_requests 큐에 적재
    "dev_organize": _h_dev_organize,                # 세나 전용 — pending → analyzed (admin 검토 대기)
    "dev_escalate": _h_dev_escalate,                # 세나 전용 — pending → needs_human_review
    "dev_clarify": _h_dev_clarify,                  # 세나 전용 — 보고자에게 추가 질문
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
    "discord_get_logs": _h_discord_get_logs,
    "discord_list_channels": _h_discord_list_channels,
    "discord_list_members": _h_discord_list_members,
    "discord_get_channel_info": _h_discord_get_channel_info,
    "discord_get_server": _h_discord_get_server,
    "discord_get_pins": _h_discord_get_pins,
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
    """registry에 모든 핸들러 주입. 봇 시작 시 1회 호출."""
    for name, fn in _MAP.items():
        set_handler(name, fn)
