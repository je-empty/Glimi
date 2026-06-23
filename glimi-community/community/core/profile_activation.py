# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
profile_activation (core) — discord-free agent create / delete / sample-image apply.

The neutral spine of the old ``mgr_system._cmd_profile_create`` /
``_cmd_profile_delete`` / ``_greet_new_persona`` / ``_apply_sample_profile_image``:
DB registration + relationship seeding + profile save are 100% discord-free; the
dm-channel ensure + first-greet + avatar refresh route through a
:class:`ChannelAdapter` (web no-op for avatar; discord pushes webhook avatar).

NEVER ``import discord`` / ``community.bot.*`` at module level.
"""
from __future__ import annotations

import asyncio
import json
import os

from community import db, log_writer
from community import community
from community.core.runtime import runtime
from community.core.channels import MGR_ID
from community.core.profile import get_user_id, get_user_name


def _sanitize_dm_name(agent_name: str) -> str:
    from community.core.channels import _norm_name_for_channel
    if not agent_name:
        return "dm-unknown"
    s = _norm_name_for_channel(agent_name)
    return f"dm-{s}" if s else "dm-unknown"


async def activate_agent_from_json(json_str: str, ctx) -> None:
    """프로필 JSON → DB 등록 + 관계 시드 + 활성화 + dm 채널 + 첫 인사 (adapter-routed)."""
    channels = ctx.channels
    creator_id = "agent-creator-001"
    try:
        text = json_str.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        profile = json.loads(text)
        if not profile.get("id") or not profile.get("name"):
            await channels.send_as_agent(ctx.channel_name, creator_id, "프로필에 id랑 name은 필수야")
            return

        existing = db.get_agent_by_name(profile["name"])
        if existing and existing.get("id") != profile["id"] and existing.get("type") == "persona":
            log_writer.system(
                f"[create_agent_profile] 중복 skip: '{profile['name']}' 이미 존재 (id={existing['id']})"
            )
            return

        from community.core.profile import save_profile
        save_profile(profile)

        agent_type = profile.get("type", "persona")
        db.register_agent(profile["id"], agent_type, profile["name"])

        if agent_type == "persona":
            r2o = profile.get("relationship_to_owner")
            if isinstance(r2o, dict):
                rel_type = r2o.get("type") or "친구"
                rel_intimacy = r2o.get("intimacy", db.INTIMACY_SCALE_DEFAULT)
                rel_dynamics = r2o.get("dynamics", "")
            else:
                rel_type, rel_intimacy, rel_dynamics = "친구", db.INTIMACY_SCALE_DEFAULT, ""
            db.add_relationship(get_user_id(), profile["id"], rel_type,
                                intimacy=rel_intimacy, dynamics=rel_dynamics)

            try:
                for t in (profile.get("relationship_templates") or []):
                    if not isinstance(t, dict) or t.get("is_owner_relationship"):
                        continue
                    target_id = t.get("target_id")
                    if not target_id or not db.get_agent(target_id):
                        continue
                    if db.get_relationship(profile["id"], target_id) or db.get_relationship(target_id, profile["id"]):
                        continue
                    inter_intimacy = int(t.get("intimacy", 60))
                    db.add_relationship(profile["id"], target_id, t.get("rel_type") or "친구",
                                        intimacy=inter_intimacy,
                                        dynamics=t.get("dynamics") or t.get("note") or "")
                    log_writer.system(
                        f"[create] 페르소나간 관계 시드: {profile['name']} ↔ {target_id} "
                        f"({t.get('rel_type', '친구')}, {inter_intimacy})"
                    )
            except Exception as e:
                log_writer.system(f"[create] persona-persona 관계 시드 실패: {type(e).__name__}: {e}")

        runtime.activate_agent(profile["id"])
        try:
            runtime.refresh_agent(MGR_ID)
        except Exception:
            pass

        new_dm_name = None
        if agent_type == "persona":
            dm_name = _sanitize_dm_name(profile["name"])
            ref = await channels.ensure_channel(dm_name, participants=[profile["id"]])
            db.set_channel_participants(dm_name, [profile["id"]])
            if getattr(ref, "created", False):
                log_writer.system(f"dm 채널 생성: {dm_name}")
            new_dm_name = dm_name

        log_writer.system(f"프로필 생성: {profile['name']} ({profile['id']})")

        if new_dm_name and agent_type == "persona":
            asyncio.create_task(
                _greet_new_persona(channels, profile["id"], profile["name"], new_dm_name)
            )
    except Exception as e:
        log_writer.system(f"[프로필생성] 실패: {type(e).__name__}: {str(e)[:100]}")
        try:
            await channels.send_as_agent(ctx.channel_name, creator_id, "프로필 생성에 문제가 있었어... 다시 해볼게")
        except Exception:
            pass


async def _greet_new_persona(channels, agent_id, agent_name, dm_name) -> None:
    """새 persona 가 자기 dm 채널에서 오너에게 첫 인사 (adapter-routed)."""
    try:
        await asyncio.sleep(3)
        if not await channels.find_channel(dm_name):
            log_writer.system(f"[not_found] kind=dm_channel name={dm_name} phase=greet_skip")
            return
        from community.core.profile import get_user_name as _gun, get_owner_call_name
        from community.core.prompts.en.persona_events import persona_first_greeting_prompt
        owner_name = _gun() or "user"
        call = get_owner_call_name() or owner_name
        prompt = persona_first_greeting_prompt(dm_name=dm_name, call=call)
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(agent_id, dm_name, prompt, log_user_message=False)
        )
        sent = 0
        for resp in responses:
            resp = resp.strip()
            if not resp:
                continue
            await channels.send_as_agent(dm_name, agent_id, resp)
            sent += 1
        if sent == 0:
            log_writer.system(f"⚠ 새친구 {agent_name} dm 인사 0건 — 응답 비어있음")
        else:
            log_writer.system(f"새친구 {agent_name}({agent_id}) #{dm_name}에서 {sent}건 인사")
    except Exception as e:
        log_writer.system(f"[새친구인사] 실패: {type(e).__name__}: {e}")


async def deactivate_agent(name: str, ctx) -> None:
    """프로필 파일 삭제 + status=archived (DB only; report via adapter)."""
    creator_id = "agent-creator-001"
    agent_name = (name or "").strip()
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name or agent_name in a["name"]), None)
    if not target:
        log_writer.system(f"[not_found] kind=agent name={agent_name}")
        return
    try:
        profile_path = community.get_community_dir() / "profiles" / f"{target['id']}.json"
        if profile_path.exists():
            profile_path.unlink()
    except Exception:
        pass
    conn = db.get_conn()
    conn.execute("UPDATE agents SET status = 'archived' WHERE id = ?", (target["id"],))
    conn.commit()
    conn.close()
    from community.core.profile import invalidate_cache
    invalidate_cache(target["id"])
    try:
        runtime.refresh_agent(MGR_ID)
    except Exception:
        pass
    await ctx.channels.send_as_agent(ctx.channel_name, creator_id,
                                     f"{target['name']} 프로필 삭제 + 비활성화 완료")
    log_writer.system(f"프로필 삭제: {target['name']} ({target['id']})")


async def apply_sample_profile_image(name: str, sample_file: str, ctx,
                                     caller_agent_id: str = "") -> None:
    """샘플 프로필 이미지를 에이전트에 적용 (파일 복사 + DB) + avatar refresh (adapter)."""
    import shutil
    from community.core.mgr_actions import _resolve_agent_name
    agent_name = _resolve_agent_name(name)
    if not agent_name or not sample_file:
        await ctx.channels.send_as_agent(ctx.channel_name, MGR_ID, "에이전트 이름이랑 샘플 파일명이 필요해")
        return
    target = next((a for a in db.list_agents() if a["name"] == agent_name), None)
    if not target:
        log_writer.system(f"[not_found] kind=agent name={agent_name}")
        return

    # 샘플 파일 위치 — community 패키지 루트의 assets/sample_profile_images
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sample_dir = os.path.join(project_root, "assets", "sample_profile_images")
    sample_path = os.path.join(sample_dir, sample_file)
    if not os.path.exists(sample_path):
        log_writer.system(f"[not_found] kind=sample name={sample_file}")
        return

    profile_image_filename = f"{target['id']}.png"
    dst_dir = community.get_profile_images_dir()
    dst = os.path.join(dst_dir, profile_image_filename)
    shutil.copy2(sample_path, dst)

    base, ext = os.path.splitext(sample_file)
    sample_full_path = os.path.join(sample_dir, f"{base}-full{ext}")
    if os.path.exists(sample_full_path):
        shutil.copy2(sample_full_path, os.path.join(dst_dir, f"{target['id']}-full.png"))

    conn = db.get_conn()
    conn.execute(
        "UPDATE agents SET profile_image_filename=?, sample_source_file=? WHERE id=?",
        (profile_image_filename, sample_file, target["id"]),
    )
    conn.commit()
    conn.close()
    log_writer.system(f"✓ 샘플 프로필 이미지 적용: {agent_name} ← {sample_file}")

    # avatar 즉시 갱신 — web no-op (라이브 /api/avatar), discord webhook push.
    try:
        await ctx.channels.refresh_agent_avatar(target["id"])
    except Exception as e:
        log_writer.system(f"  avatar refresh 실패 (무시): {e}")

    sender_id = caller_agent_id or ("agent-creator-001" if target["type"] == "persona" else target["id"])
    await ctx.channels.send_as_agent(ctx.channel_name, sender_id, f"{agent_name} 프로필 이미지 적용했어!")
