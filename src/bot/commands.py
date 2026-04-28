"""
Project Glimi — Bot Commands
discord_bot.py에서 추출한 @bot.command 핸들러 모음
"""
import os
import io
import asyncio
import random

import discord
from PIL import Image

from src import db, community
from src import log_writer
from src.core.profile import load_profile, get_user_name, get_user_id
from src.core.runtime import runtime
from src.core.conversation import (
    start_conversation, stop_conversation, list_active_conversations,
)
from src.bot import (
    bot, log, MGR_CHANNEL, MGR_ID,
    CHANNEL_AGENT_MAP, AGENT_CHANNEL_MAP, GROUP_PARTICIPANTS,
    _webhook_cache,
)
from src.bot.core import (
    send_as_agent, get_agent_webhook, _get_profile_image_bytes, _split_for_chat,
)
from src.bot.mgr_system import (
    parse_and_execute_actions, yuna_dev_request,
    _forward_action_to_yuna,
)


# ── 슬래시/명령어 ────────────────────────────────────

@bot.command(name="상태")
async def cmd_status(ctx):
    """에이전트 상태 조회"""
    agents = db.list_agents("persona")
    lines = ["📋 **에이전트 상태**", ""]
    for a in agents:
        icon = "🟢" if a["status"] == "active" else "⚪"
        lines.append(f"{icon} **{a['name']}** — {a['current_emotion']}({a['emotion_intensity']}/10)")
    await ctx.send("\n".join(lines))


@bot.command(name="관계")
async def cmd_relationships(ctx):
    """관계 현황 조회"""
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM relationships ORDER BY intimacy_score DESC").fetchall()
    conn.close()

    lines = ["💕 **관계 현황**", ""]
    for r in rows:
        a = get_user_name() if r["agent_a"] == get_user_id() else (db.get_agent(r["agent_a"]) or {}).get("name", r["agent_a"])
        b = (db.get_agent(r["agent_b"]) or {}).get("name", r["agent_b"])
        bar = "█" * (r["intimacy_score"] // 10) + "░" * (10 - r["intimacy_score"] // 10)
        lines.append(f"{a} ↔ {b}: {r['type']} [{bar}] {r['intimacy_score']}")

    await ctx.send("\n".join(lines))


@bot.command(name="보고")
async def cmd_report(ctx):
    """관리자(서유나) 보고 요청"""
    mgr_id = "agent-mgr-001"

    async with ctx.typing():
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(mgr_id, MGR_CHANNEL, "오늘 상태 보고해줘")
        )

    for msg in responses:
        await send_as_agent(ctx.channel, mgr_id, msg)
        await asyncio.sleep(0.5)


@bot.command(name="감정")
async def cmd_emotion(ctx, agent_name: str, emotion: str, intensity: int = 5):
    """에이전트 감정 변경 — !감정 은하윤 서운함 7"""
    # 이름으로 에이전트 찾기
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if not target:
        await ctx.send(f"에이전트를 찾을 수 없음: {agent_name}")
        return

    intensity = max(1, min(10, intensity))
    db.update_emotion(target["id"], emotion, intensity)
    runtime.refresh_agent(target["id"])
    await ctx.send(f"✅ {agent_name} 감정 변경: {emotion} ({intensity}/10)")


@bot.command(name="내부대화")
async def cmd_internal(ctx, speaker_name: str, listener_name: str, *, context: str = ""):
    """에이전트 간 대화 트리거 — !내부대화 최지수 은하윤 오너 자랑하려고"""
    agents = db.list_agents()
    speaker = next((a for a in agents if a["name"] == speaker_name), None)
    listener = next((a for a in agents if a["name"] == listener_name), None)

    if not speaker or not listener:
        await ctx.send("에이전트 이름을 확인해주세요")
        return

    from src.bot import internal_dm_channel_name
    channel_name = internal_dm_channel_name(speaker_name, listener_name)
    channel_name_alt = f"internal-dm-{listener_name}-{speaker_name}"  # 구 order 호환
    channel_name_alt2 = f"internal-dm-{speaker_name}-{listener_name}"

    async with ctx.typing():
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_agent_to_agent(
                speaker["id"], listener["id"], channel_name, context
            )
        )

    # internal-dm 채널 찾기 또는 현재 채널에 출력
    target_ch = (discord.utils.get(ctx.guild.text_channels, name=channel_name)
                 or discord.utils.get(ctx.guild.text_channels, name=channel_name_alt)
                 or discord.utils.get(ctx.guild.text_channels, name=channel_name_alt2))
    out_ch = target_ch or ctx.channel

    for msg in responses:
        await send_as_agent(out_ch, speaker["id"], msg)
        await asyncio.sleep(0.6)


@bot.command(name="도움")
async def cmd_help_glimi(ctx):
    """Glimi 명령어 도움말"""
    help_text = """🌀 **Project Glimi 명령어**

**채팅**: 각 dm-채널에서 그냥 메시지 보내면 됨
**!상태** — 에이전트 감정 상태 조회
**!관계** — 관계 현황 + 친밀도
**!보고** — 관리자(서유나) 상태 보고
**!감정** 이름 감정 강도 — 감정 변경
**!강제** 메시지 — dm: 이름 생략 / 그룹: !강제 이름 내용 (거부 불가)

**💬 톡방/대화**
**!톡방** 이름1 이름2 [주제] — 톡방 생성 (예: !톡방 은하윤 최지수 수다)
**!톡방삭제** 채널명 — 톡방 삭제
**!대화시작** 이름1 이름2 [상황] — 에이전트 자동 대화 시작
**!대화중단** [채널명] — 자동 대화 중단
**!대화현황** — 진행 중인 자동 대화 목록
**!내부대화** 이름1 이름2 상황 — 1회성 에이전트 간 대화

**🔧 관리**
**!에이전트생성** 컨셉 — 새 에이전트 생성
**!에이전트제거** 이름 — 비활성화
**!에이전트복구** 이름 — 복구
**!프로필** 이름 — 프로필 상세
**!분석** — 유나가 전체 상황 분석 + 새 에이전트 제안

**🖼️ 아바타**
**!아바타생성** 이름 — 이미지 프롬프트 생성
**!아바타전체생성** — 전체 프롬프트 일괄 생성
**!아바타설정** 이름 — 이미지 첨부로 아바타 설정
**!아바타로드** — 로컬 이미지 일괄 등록
**!아바타적용** — 모든 채널 Webhook에 아바타 일괄 적용
**!도움** — 이 메시지"""
    await ctx.send(help_text)


# ── 관리자 명령어 (서유나 권한) ───────────────────────

@bot.command(name="에이전트생성")
async def cmd_create_agent(ctx, *, concept: str):
    """새 에이전트 생성 — 윤하나(creator)가 프로필 생성"""
    creator_id = "agent-creator-001"
    hana_id = creator_id  # 하나 담당

    # 하나가 접수
    await send_as_agent(ctx.channel, hana_id, f"에이전트 생성 요청 접수! 만들어볼게~")
    await asyncio.sleep(0.5)
    await send_as_agent(ctx.channel, hana_id, f"컨셉: {concept}")

    # 기존 에이전트 번호 파악
    existing = db.list_agents("persona")
    next_num = len(existing) + 1
    new_id = f"agent-persona-{next_num:03d}"

    # 윤하나(creator)에게 생성 요청
    runtime.activate_agent(creator_id)

    from src.core.prompts.en.commands.create_agent import create_agent_prompt
    create_prompt = create_agent_prompt(new_id=new_id, concept=concept)

    async with ctx.typing():
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(creator_id, "mgr-creator", create_prompt, model_override="claude-opus-4-6")
        )

    raw_response = "\n".join(responses)

    # JSON 파싱 시도
    import json as json_module
    try:
        # JSON 블록 추출 (```json ... ``` 또는 { ... })
        json_text = raw_response
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0]
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0]

        # { 부터 마지막 } 까지 추출
        start = json_text.find("{")
        end = json_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_text = json_text[start:end]

        profile = json_module.loads(json_text)
        profile["id"] = new_id  # ID 강제 설정

        # 프로필 저장
        from src.core.profile import save_profile
        save_profile(profile)

        # DB 등록
        db.register_agent(new_id, "persona", profile["name"])

        # 관계 설정
        if "relationship_to_owner" in profile:
            db.add_relationship(
                get_user_id(), new_id,
                profile["relationship_to_owner"]["type"],
                intimacy=50,
                dynamics=profile["relationship_to_owner"].get("dynamics", "")
            )

        # 채널 매핑 갱신
        ch_name = f"dm-{profile['name']}"
        CHANNEL_AGENT_MAP[ch_name] = new_id
        AGENT_CHANNEL_MAP[new_id] = ch_name

        # 채널 생성 — ensure_unique_channel 로 중복 방지 (이미 있으면 재사용)
        guild = ctx.guild
        from src.bot.core import _get_category_for_channel, _ensure_category
        from src.core.sync import ensure_unique_channel
        category = await _ensure_category(guild, _get_category_for_channel(ch_name))
        if category:
            await ensure_unique_channel(guild, ch_name, category)

        # 서유나 보고
        await send_as_agent(ctx.channel, hana_id,
            f"생성 완료! {profile['name']} ({new_id})")
        await asyncio.sleep(0.3)

        # 요약 정보
        summary_parts = [f"**{profile['name']}** 등록됨"]
        if profile.get("age"):
            summary_parts.append(f"나이: {profile['age']}살")
        if profile.get("mbti"):
            summary_parts.append(f"MBTI: {profile['mbti']}")
        if profile.get("relationship_to_owner", {}).get("type"):
            summary_parts.append(f"관계: {profile['relationship_to_owner']['type']}")

        # 새 에이전트 활성화 + 유나/하나 프롬프트 갱신
        runtime.activate_agent(new_id)
        runtime.refresh_agent("agent-mgr-001")
        runtime.refresh_agent(hana_id)

        await send_as_agent(ctx.channel, hana_id, " / ".join(summary_parts))
        await send_as_agent(ctx.channel, hana_id, f"dm-{profile['name']} 채널에서 대화할 수 있어")

    except (json_module.JSONDecodeError, KeyError) as e:
        await send_as_agent(ctx.channel, hana_id,
            f"프로필 생성 실패.. JSON 파싱 에러야. 다시 시도해볼까?")
        await send_as_agent(ctx.channel, hana_id, f"에러: {str(e)[:100]}")
        log.error(f"에이전트 생성 JSON 파싱 실패: {e}")


@bot.command(name="에이전트제거")
async def cmd_remove_agent(ctx, agent_name: str):
    """에이전트 비활성화"""
    hana_id = "agent-creator-001"
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if not target:
        await send_as_agent(ctx.channel, hana_id, f"{agent_name}? 그런 에이전트 없는데")
        return

    if target["type"] != "persona":
        await send_as_agent(ctx.channel, hana_id, "페르소나 에이전트만 제거할 수 있어")
        return

    # DB에서 비활성화
    conn = db.get_conn()
    conn.execute("UPDATE agents SET status = 'inactive' WHERE id = ?", (target["id"],))
    conn.commit()
    conn.close()

    # 채널 매핑에서 제거
    ch_name = f"dm-{agent_name}"
    CHANNEL_AGENT_MAP.pop(ch_name, None)
    AGENT_CHANNEL_MAP.pop(target["id"], None)

    # 런타임에서 제거
    if target["id"] in runtime._active_agents:
        del runtime._active_agents[target["id"]]

    await send_as_agent(ctx.channel, hana_id, f"{agent_name} 비활성화 완료")
    await send_as_agent(ctx.channel, hana_id, "프로필 파일은 남아있으니까 !에이전트복구로 다시 살릴 수 있어")


@bot.command(name="에이전트복구")
async def cmd_restore_agent(ctx, agent_name: str):
    """비활성화된 에이전트 복구"""
    hana_id = "agent-creator-001"

    conn = db.get_conn()
    row = conn.execute("SELECT * FROM agents WHERE name = ? AND status = 'inactive'", (agent_name,)).fetchone()

    if not row:
        await send_as_agent(ctx.channel, hana_id, f"비활성화된 {agent_name}를 못 찾겠어")
        conn.close()
        return

    conn.execute("UPDATE agents SET status = 'active' WHERE id = ?", (row["id"],))
    conn.commit()
    conn.close()

    # 채널 매핑 복구
    ch_name = f"dm-{agent_name}"
    CHANNEL_AGENT_MAP[ch_name] = row["id"]
    AGENT_CHANNEL_MAP[row["id"]] = ch_name
    runtime.activate_agent(row["id"])

    await send_as_agent(ctx.channel, hana_id, f"{agent_name} 복구 완료! 다시 대화할 수 있어")


@bot.command(name="프로필")
async def cmd_profile(ctx, agent_name: str):
    """에이전트 프로필 상세 보기"""
    hana_id = "agent-creator-001"
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if not target:
        await send_as_agent(ctx.channel, hana_id, f"{agent_name}? 모르는 애인데")
        return

    profile = load_profile(target["id"])
    if not profile:
        await send_as_agent(ctx.channel, hana_id, "프로필 파일을 못 찾겠어")
        return

    lines = [f"📋 **{profile['name']}** ({target['id']})"]
    lines.append(f"상태: {target['status']}")

    if profile.get("age"):
        lines.append(f"나이: {profile['age']}살 ({profile.get('birth_year', '?')}년생)")
    if profile.get("mbti"):
        lines.append(f"MBTI: {profile['mbti']}")
    if profile.get("personality", {}).get("traits"):
        lines.append(f"성격: {', '.join(profile['personality']['traits'])}")
    if profile.get("appearance", {}).get("summary"):
        lines.append(f"외모: {profile['appearance']['summary']}")
    if profile.get("speech", {}).get("style_description"):
        lines.append(f"말투: {profile['speech']['style_description']}")
    if profile.get("relationship_to_owner", {}).get("type"):
        rel = profile["relationship_to_owner"]
        lines.append(f"관계: {rel['type']} ({rel.get('duration', '')})")

    await ctx.send("\n".join(lines))


# ── 아바타 명령어 ────────────────────────────────────

@bot.command(name="아바타생성")
async def cmd_avatar_prompt(ctx, agent_name: str):
    """에이전트 프로필 기반 이미지 생성 프롬프트 제작 — 하나(creator) 담당"""
    creator_id = "agent-creator-001"
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if not target:
        await send_as_agent(ctx.channel, creator_id, f"{agent_name}? 그런 사람 없는데")
        return

    profile = load_profile(target["id"])
    if not profile:
        await send_as_agent(ctx.channel, creator_id, "프로필을 못 찾겠어")
        return

    appearance = profile.get("appearance", {})
    personality = profile.get("personality", {})
    name = profile["name"]
    age = profile.get("age", "?")

    # outfit_hint 결정 (나이 기반)
    if isinstance(age, int):
        if age <= 15:
            outfit_hint = "middle school uniform or casual hoodie"
        elif age <= 18:
            outfit_hint = "school uniform (white shirt, dark navy blazer)"
        elif age <= 23:
            outfit_hint = "casual university student outfit, cardigan or knit"
        else:
            outfit_hint = "casual adult outfit, office-casual"
    else:
        outfit_hint = "casual outfit"

    runtime.activate_agent(creator_id)

    # 하나에게 아바타 프롬프트 생성 요청
    avatar_request = (
        f"{name}의 아바타 이미지 프롬프트를 만들어줘.\n\n"
        f"정보:\n"
        f"- 나이: {age}살\n"
        f"- 외모: {appearance.get('summary', '?')}\n"
        f"- 헤어: {appearance.get('hair', '?')}\n"
        f"- 패션: {appearance.get('fashion_style', '?')}\n"
        f"- 성격: {', '.join(personality.get('traits', []))}\n\n"
        f"2줄 프롬프트만 출력해. 다른 말 하지 마."
    )

    async with ctx.typing():
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(creator_id, "mgr-creator", avatar_request)
        )

    # 하나의 응답에서 프롬프트 추출
    char_detail = ""
    for r in responses:
        cleaned = r.strip().strip('"').strip("'").strip("`")
        if len(cleaned) > 20:
            char_detail = cleaned
            break
    if not char_detail:
        char_detail = "\n".join(responses)

    # 검증된 프롬프트 템플릿
    from src.core.prompts.en.external.image_gen import profile_image_prompt
    full_prompt = profile_image_prompt(age=age, outfit_hint=outfit_hint, char_detail=char_detail)

    await send_as_agent(ctx.channel, creator_id, f"{name} 프롬프트 만들었어. 복붙해서 써:")
    await ctx.send(f"**{name} — 프롬프트**\n```\n{full_prompt}\n```")
    await send_as_agent(ctx.channel, creator_id,
        "ChatGPT나 Gemini에 넣으면 돼. "
        "이미지 만들면 여기 올리고 !아바타설정 " + agent_name + " 치면 등록해줄게")


@bot.command(name="아바타설정")
async def cmd_set_avatar(ctx, agent_name: str):
    """에이전트 아바타 설정 — 이미지 첨부 or 답장 → 1:1 크롭 → 로컬 저장 → 등록"""
    hana_id = "agent-creator-001"
    agents = db.list_agents()
    target = next((a for a in agents if a["name"] == agent_name), None)

    if not target:
        await send_as_agent(ctx.channel, hana_id, f"{agent_name}? 모르는 애인데")
        return

    # ── 이미지 소스 찾기 ──
    attachment = None

    # 1. 직접 첨부
    if ctx.message.attachments:
        att = ctx.message.attachments[0]
        if att.content_type and att.content_type.startswith("image/"):
            attachment = att
        else:
            await send_as_agent(ctx.channel, hana_id, "이미지 파일만 가능해")
            return

    # 2. 답장한 메시지의 이미지
    elif ctx.message.reference:
        try:
            ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if ref_msg.attachments:
                for att in ref_msg.attachments:
                    if att.content_type and att.content_type.startswith("image/"):
                        attachment = att
                        break
        except Exception:
            pass

    if not attachment:
        await send_as_agent(ctx.channel, hana_id,
            "이미지를 첨부하거나, 이미지가 있는 메시지에 답장으로 !아바타설정 " + agent_name + " 써줘")
        return

    await send_as_agent(ctx.channel, hana_id, f"{agent_name} 아바타 처리 중..")

    try:
        # ── 이미지 다운로드 ──
        img_bytes = await attachment.read()

        # ── 1:1 센터 크롭 ──
        img = Image.open(io.BytesIO(img_bytes))
        img = img.convert("RGBA")
        w, h = img.size

        if w != h:
            # 짧은 쪽 기준으로 정사각형 크롭
            size = min(w, h)
            left = (w - size) // 2
            top = (h - size) // 2
            img = img.crop((left, top, left + size, top + size))
            await send_as_agent(ctx.channel, hana_id,
                f"원본 {w}x{h} → {size}x{size} 크롭 완료")

        # 디스코드 아바타 적정 사이즈로 리사이즈 (512x512)
        if img.size[0] > 512:
            img = img.resize((512, 512), Image.Resampling.LANCZOS)

        # ── 로컬 저장 ──
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        img_dir = os.path.join(project_root, "profiles", "agent-profile-image")
        os.makedirs(img_dir, exist_ok=True)

        local_path = os.path.join(img_dir, f"{target['id']}.png")
        img.save(local_path, "PNG")

        # ── 크롭된 이미지 디스코드에 업로드 ──
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)

        discord_file = discord.File(buf, filename=f"{target['id']}.png")
        upload_msg = await ctx.channel.send(
            f"✅ {agent_name} 아바타", file=discord_file
        )

        # ── 프로필에 URL 저장 ──
        if upload_msg.attachments:
            avatar_url = upload_msg.attachments[0].url

            profile = load_profile(target["id"])
            if profile:
                profile["profile_image_url"] = avatar_url
                profile["profile_image_filename"] = f"{target['id']}.png"
                from src.core.profile import save_profile
                save_profile(profile)

                await send_as_agent(ctx.channel, hana_id,
                    f"{agent_name} 아바타 설정 완료! 로컬 저장 + 프로필 등록 다 했어")
                await send_as_agent(ctx.channel, hana_id,
                    "다음 메시지부터 적용돼")
            else:
                await send_as_agent(ctx.channel, hana_id, "프로필 저장 실패..")
        else:
            await send_as_agent(ctx.channel, hana_id, "업로드 실패..")

    except Exception as e:
        await send_as_agent(ctx.channel, hana_id, f"아바타 처리 중 오류: {str(e)[:100]}")
        log.error(f"아바타 설정 오류: {e}")


@bot.command(name="아바타전체생성")
async def cmd_avatar_all(ctx):
    """모든 에이전트의 아바타 프롬프트 일괄 생성"""
    hana_id = "agent-creator-001"
    agents = db.list_agents("persona")

    mgr_agent = db.get_agent(hana_id)
    if mgr_agent:
        agents.append(mgr_agent)

    await send_as_agent(ctx.channel, hana_id,
        f"전체 {len(agents)}명 프롬프트 만들게. 좀 걸려")

    for agent in agents:
        profile = load_profile(agent["id"])
        if not profile:
            continue
        if profile.get("profile_image_url"):
            await send_as_agent(ctx.channel, hana_id,
                f"{agent['name']} — 이미 아바타 있어. 스킵")
            continue

        name = profile["name"]
        age = profile.get("age", "?")
        appearance = profile.get("appearance", {})
        personality = profile.get("personality", {})

        if isinstance(age, int):
            if age <= 15:
                outfit_hint = "middle school uniform or casual hoodie"
            elif age <= 18:
                outfit_hint = "school uniform (white shirt, dark navy blazer)"
            elif age <= 23:
                outfit_hint = "casual university student outfit, cardigan or knit"
            else:
                outfit_hint = "casual adult outfit, office-casual"
        else:
            outfit_hint = "casual outfit"

        char_request = (
            f"{name} 캐릭터 묘사를 영어 한 줄로. 다른 말 없이:\n"
            f"나이: {age}살 / 외모: {appearance.get('summary', '?')} / "
            f"헤어: {appearance.get('hair', '?')} / "
            f"성격: {', '.join(personality.get('traits', []))}\n"
            f"형식: 헤어스타일, 표정/눈빛, 배경 accent color"
        )

        async with ctx.typing():
            loop = asyncio.get_event_loop()
            responses = await loop.run_in_executor(
                None,
                lambda req=char_request: runtime.generate_response(
                    hana_id, "mgr-dashboard", req
                )
            )

        char_detail = ""
        for r in responses:
            cleaned = r.strip().strip('"').strip("'").strip("`")
            if len(cleaned) > 20 and not cleaned.startswith(("[", "(")):
                char_detail = cleaned
                break
        if not char_detail:
            char_detail = " ".join(r.strip() for r in responses)

        base = (
            f"Anime-style profile illustration, Korean girl, age {age}, "
            f"{outfit_hint}, clean lineart, soft cel shading, "
            f"pastel gradient background, bust-up shot, slightly asymmetrical natural pose, "
            f"subtle catchlight in eyes, consistent art style similar to modern slice-of-life anime "
            f"(like Horimiya or Oregairu visual style)"
        )

        await ctx.send(f"**{name}**\n```\n{base}\n{char_detail}\n```")
        await asyncio.sleep(0.3)

    await send_as_agent(ctx.channel, hana_id,
        "전부 끝! 이미지 만들고 !아바타설정 이름 으로 설정해줘")


@bot.command(name="아바타로드")
async def cmd_avatar_load(ctx):
    """로컬 이미지 파일을 디스코드에 업로드하고 아바타로 설정

    커뮤니티 avatars/ 폴더에서
    agent-persona-001.png 같은 파일명을 자동 매칭
    """
    hana_id = "agent-creator-001"

    # 이미지 폴더 경로 (커뮤니티 → assets 순서로 탐색)
    image_dir = str(community.get_profile_images_dir())

    if not os.path.exists(image_dir):
        await send_as_agent(ctx.channel, hana_id,
            f"이미지 폴더가 없어: {image_dir}")
        return

    # 이미지 파일 스캔
    image_files = [f for f in os.listdir(image_dir)
                   if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))]

    if not image_files:
        await send_as_agent(ctx.channel, hana_id, "폴더에 이미지 파일이 없어")
        return

    await send_as_agent(ctx.channel, hana_id,
        f"이미지 {len(image_files)}개 발견. 업로드 시작할게")

    agents = db.list_agents()
    success = 0

    for img_file in sorted(image_files):
        # 파일명에서 agent ID 추출 (agent-persona-001.png → agent-persona-001)
        agent_id = os.path.splitext(img_file)[0]
        target = next((a for a in agents if a["id"] == agent_id), None)

        if not target:
            await send_as_agent(ctx.channel, hana_id,
                f"⏭ {img_file} — 매칭되는 에이전트 없어서 스킵")
            continue

        file_path = os.path.join(image_dir, img_file)

        try:
            # 이미지 열기 + 1:1 크롭
            img = Image.open(file_path).convert("RGBA")
            w, h = img.size
            if w != h:
                size = min(w, h)
                left = (w - size) // 2
                top = (h - size) // 2
                img = img.crop((left, top, left + size, top + size))
            if img.size[0] > 512:
                img = img.resize((512, 512), Image.Resampling.LANCZOS)

            # 크롭된 이미지를 로컬에 덮어쓰기 저장
            cropped_path = os.path.join(image_dir, f"{agent_id}.png")
            img.save(cropped_path, "PNG")

            # 디스코드에 업로드
            buf = io.BytesIO()
            img.save(buf, "PNG")
            buf.seek(0)
            discord_file = discord.File(buf, filename=f"{agent_id}.png")
            upload_msg = await ctx.channel.send(
                f"📸 {target['name']} 아바타 ({w}x{h} → {img.size[0]}x{img.size[0]})",
                file=discord_file
            )

            # 업로드된 이미지 URL 가져오기
            if upload_msg.attachments:
                avatar_url = upload_msg.attachments[0].url

                # 프로필에 저장
                profile = load_profile(agent_id)
                if profile:
                    profile["profile_image_url"] = avatar_url
                    profile["profile_image_filename"] = f"{agent_id}.png"
                    from src.core.profile import save_profile
                    save_profile(profile)
                    success += 1
                    await send_as_agent(ctx.channel, hana_id,
                        f"✅ {target['name']} 아바타 설정 완료")
                else:
                    await send_as_agent(ctx.channel, hana_id,
                        f"❌ {target['name']} 프로필 저장 실패")
            else:
                await send_as_agent(ctx.channel, hana_id,
                    f"❌ {target['name']} 업로드 실패")

        except Exception as e:
            await send_as_agent(ctx.channel, hana_id,
                f"❌ {target['name']} 오류: {str(e)[:80]}")

        await asyncio.sleep(0.5)

    await send_as_agent(ctx.channel, hana_id,
        f"완료! {success}/{len(image_files)}개 아바타 설정됨. 다음 메시지부터 적용돼")


@bot.command(name="아바타적용")
async def cmd_apply_avatars(ctx):
    """모든 채널의 에이전트 Webhook에 로컬 이미지 일괄 적용

    커뮤니티 avatars/ 에 있는 이미지를 읽어서
    모든 채널의 해당 에이전트 Webhook 아바타를 업데이트
    """
    hana_id = "agent-creator-001"
    guild = ctx.guild
    agents = db.list_agents()

    # glimi 카테고리의 모든 채널
    category = discord.utils.get(guild.categories, name="glimi")
    if not category:
        await send_as_agent(ctx.channel, hana_id, "glimi 카테고리를 못 찾겠어")
        return

    channels = [ch for ch in guild.text_channels if ch.category == category]
    updated = 0
    skipped = 0

    await send_as_agent(ctx.channel, hana_id,
        f"전체 에이전트 아바타를 Webhook에 적용할게. 채널 {len(channels)}개 처리 중..")

    for agent in agents:
        avatar_bytes = _get_profile_image_bytes(agent["id"])
        if not avatar_bytes:
            skipped += 1
            continue

        profile = load_profile(agent["id"])
        name = profile["name"] if profile else agent["id"]

        for ch in channels:
            try:
                wh = await get_agent_webhook(ch, agent["id"])
                await wh.edit(avatar=avatar_bytes)
                # 캐시 갱신
                _webhook_cache[(ch.id, agent["id"])] = wh
                updated += 1
            except discord.errors.HTTPException as e:
                if e.status == 429:  # rate limit
                    await asyncio.sleep(5)
                    try:
                        await wh.edit(avatar=avatar_bytes)
                        updated += 1
                    except Exception:
                        pass
            except Exception as e:
                log.warning(f"Webhook 아바타 적용 실패 {name}/{ch.name}: {e}")

            await asyncio.sleep(0.5)  # rate limit 방지

        await send_as_agent(ctx.channel, hana_id, f"✅ {name} 적용 완료")

    await send_as_agent(ctx.channel, hana_id,
        f"끝! Webhook {updated}개 업데이트, 이미지 없는 에이전트 {skipped}명 스킵")


# ── 톡방 관리 (유나 권한) ─────────────────────────────

@bot.command(name="톡방")
async def cmd_create_room(ctx, *args):
    """톡방 생성 — !톡방 은하윤 최지수 [주제]

    유나가 채널 만들고, 참여 에이전트들에게 알림
    """
    mgr_id = "agent-mgr-001"

    if len(args) < 2:
        await send_as_agent(ctx.channel, mgr_id, "최소 2명 이상 이름을 넣어줘. !톡방 은하윤 최지수")
        return

    # 에이전트 이름 파싱 (마지막이 에이전트 이름이 아니면 주제로 처리)
    agents_db = db.list_agents()
    agent_names = {a["name"]: a for a in agents_db}

    participants = []
    topic_parts = []
    for arg in args:
        if arg in agent_names:
            participants.append(agent_names[arg])
        else:
            topic_parts.append(arg)

    if len(participants) < 2:
        await send_as_agent(ctx.channel, mgr_id, "에이전트를 2명 이상 찾을 수 없어. 이름 확인해줘")
        return

    topic = " ".join(topic_parts) if topic_parts else None
    names = [p["name"] for p in participants]
    ch_name = f"group-{'-'.join(names)}"

    # 채널 생성
    guild = ctx.guild
    from src.bot.core import _get_category_for_channel, _ensure_category
    category = await _ensure_category(guild, _get_category_for_channel(ch_name))
    existing = discord.utils.get(guild.text_channels, name=ch_name)

    if existing:
        await send_as_agent(ctx.channel, mgr_id, f"이미 있는 채널이야: #{ch_name}")
        return

    from src.core.sync import ensure_unique_channel
    new_ch, _ = await ensure_unique_channel(guild, ch_name, category)

    # 채널 매핑 등록 (그룹 채널)
    participant_ids = [p["id"] for p in participants]
    GROUP_PARTICIPANTS[ch_name] = participant_ids

    await send_as_agent(ctx.channel, mgr_id,
        f"톡방 만들었어: #{ch_name} ({', '.join(names)})")

    if topic:
        await send_as_agent(ctx.channel, mgr_id, f"주제: {topic}")

    # 첫 메시지로 상황 알림 (에이전트들이 인지하게)
    if topic:
        intro = f"{', '.join(names)} 톡방이 열렸어. 주제: {topic}"
    else:
        intro = f"{', '.join(names)} 톡방이 열렸어."

    await new_ch.send(f"*{intro}*")

    # 자동 대화 시작할지 물어보기
    await send_as_agent(ctx.channel, mgr_id,
        f"대화 시작하려면 !대화시작 {' '.join(names)} 입력해")


@bot.command(name="톡방삭제")
async def cmd_delete_room(ctx, channel_name: str):
    """톡방 삭제 — !톡방삭제 group-은하윤-최지수"""
    mgr_id = "agent-mgr-001"

    target_ch = discord.utils.get(ctx.guild.text_channels, name=channel_name)
    if not target_ch:
        await send_as_agent(ctx.channel, mgr_id, f"채널을 못 찾겠어: {channel_name}")
        return

    # 진행 중인 대화 중단
    stop_conversation(channel_name)

    await target_ch.delete(reason="유나 관리자 삭제")
    await send_as_agent(ctx.channel, mgr_id, f"#{channel_name} 삭제 완료")


# ── 에이전트 자동 대화 ───────────────────────────────

@bot.command(name="대화시작")
async def cmd_start_convo(ctx, *args):
    """에이전트 간 자동 대화 시작 — !대화시작 은하윤 최지수 [상황설명]

    에이전트들이 알아서 대화하고, 유나가 턴 제한으로 관리
    """
    mgr_id = "agent-mgr-001"

    if len(args) < 2:
        await send_as_agent(ctx.channel, mgr_id, "!대화시작 에이전트1 에이전트2 [상황설명]")
        return

    agents_db = db.list_agents()
    agent_names = {a["name"]: a for a in agents_db}

    participants = []
    context_parts = []
    for arg in args:
        if arg in agent_names:
            participants.append(agent_names[arg])
        else:
            context_parts.append(arg)

    if len(participants) < 2:
        await send_as_agent(ctx.channel, mgr_id, "에이전트 2명 이상 필요해")
        return

    context = " ".join(context_parts) if context_parts else ""
    names = [p["name"] for p in participants]
    participant_ids = [p["id"] for p in participants]

    # 대화할 채널 찾기 또는 생성
    ch_name = f"internal-{'-'.join(names)}"
    guild = ctx.guild
    from src.bot.core import _get_category_for_channel, _ensure_category
    from src.core.sync import ensure_unique_channel
    category = await _ensure_category(guild, _get_category_for_channel(ch_name))
    target_ch, created = await ensure_unique_channel(guild, ch_name, category)
    if created:
        await send_as_agent(ctx.channel, mgr_id, f"채널 생성: #{ch_name}")

    await send_as_agent(ctx.channel, mgr_id,
        f"{', '.join(names)} 대화 시작할게. 지켜보고 있을 거야")

    # 대화 전송 함수
    async def send_fn(agent_id: str, message: str):
        await send_as_agent(target_ch, agent_id, message)

    # 자동 대화 실행 (비동기)
    asyncio.create_task(_run_and_report(
        ctx.channel, mgr_id, ch_name, participant_ids, send_fn, context
    ))


async def _run_and_report(report_ch, mgr_id, ch_name, participant_ids, send_fn, context):
    """자동 대화 실행 후 유나가 결과 보고"""
    try:
        state = await start_conversation(
            ch_name, participant_ids, send_fn, context=context
        )
        # 대화 완료 후 유나 보고
        names = [runtime.get_agent_name(aid) for aid in participant_ids]
        await send_as_agent(report_ch, mgr_id,
            f"{', '.join(names)} 대화 끝났어. 총 {state.turn_count}턴")
    except Exception as e:
        await send_as_agent(report_ch, mgr_id, f"대화 중 오류 발생: {str(e)[:100]}")


@bot.command(name="대화중단")
async def cmd_stop_convo(ctx, channel_name: str = ""):
    """진행 중인 자동 대화 중단 — !대화중단 internal-은하윤-최지수"""
    mgr_id = "agent-mgr-001"

    if not channel_name:
        # 활성 대화 목록 보여주기
        active = list_active_conversations()
        if not active:
            await send_as_agent(ctx.channel, mgr_id, "진행 중인 대화 없어")
            return
        lines = ["진행 중인 대화:"]
        for c in active:
            lines.append(f"  #{c['channel']} — {', '.join(c['participants'])} ({c['turns']}/{c['max_turns']}턴)")
        await send_as_agent(ctx.channel, mgr_id, "\n".join(lines))
        return

    if stop_conversation(channel_name):
        await send_as_agent(ctx.channel, mgr_id, f"#{channel_name} 대화 중단시켰어")
    else:
        await send_as_agent(ctx.channel, mgr_id, f"#{channel_name}에 진행 중인 대화가 없어")


@bot.command(name="대화현황")
async def cmd_convo_status(ctx):
    """활성 대화 목록"""
    mgr_id = "agent-mgr-001"
    active = list_active_conversations()

    if not active:
        await send_as_agent(ctx.channel, mgr_id, "지금 진행 중인 대화 없어")
        return

    lines = ["📊 진행 중인 대화:"]
    for c in active:
        lines.append(f"  #{c['channel']} — {', '.join(c['participants'])} ({c['turns']}/{c['max_turns']}턴)")
    await send_as_agent(ctx.channel, mgr_id, "\n".join(lines))


# ── 강제 답변 킬스위치 ───────────────────────────────

@bot.command(name="강제")
async def cmd_force(ctx, *, message: str):
    """에이전트에게 강제 답변 요구 — dm: !강제 내용 / 그룹: !강제 이름 내용"""
    channel_name = ctx.channel.name

    # dm 채널: 이름 생략 가능 (채널명에서 에이전트 자동 추출)
    if channel_name in CHANNEL_AGENT_MAP:
        agent_id = CHANNEL_AGENT_MAP[channel_name]
        actual_message = message
    elif channel_name.startswith("group-") and channel_name in GROUP_PARTICIPANTS:
        # 그룹채팅: !강제 이름 지시내용 형식
        parts = message.split(None, 1)
        if len(parts) < 2:
            await ctx.send("그룹채팅에서는 `!강제 이름 지시내용` 형식으로 써줘")
            return
        agent_name, actual_message = parts
        # 이름으로 에이전트 찾기
        agents = db.list_agents()
        target = next((a for a in agents if a["name"] == agent_name), None)
        if not target:
            await ctx.send(f"에이전트를 찾을 수 없음: {agent_name}")
            return
        agent_id = target["id"]
        if agent_id not in GROUP_PARTICIPANTS[channel_name]:
            await ctx.send(f"{agent_name}은(는) 이 톡방 참여자가 아님")
            return
    else:
        await ctx.send("dm 채널이나 그룹채팅에서만 사용 가능해")
        return

    profile = load_profile(agent_id)
    if not profile:
        return

    # 원본 메시지만 DB에 로깅
    db.log_message(channel_name, get_user_id(), actual_message)
    log_writer.chat(channel_name, get_user_name(), actual_message)

    # 강제 지시는 generate_response_force로 처리 — 시스템 레벨 주입
    async with ctx.typing():
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response_force(agent_id, channel_name, actual_message)
        )

    # 빈 응답 = timeout/에러 — 메타 문구 뿌리는 대신 오너에게 에러 알림.
    if not responses:
        await ctx.send(f"⚠ {agent_name} 응답 생성 실패 (타임아웃/에러). 잠시 후 다시 시도해줘.")
        return

    for i, msg in enumerate(responses):
        if i > 0:
            await asyncio.sleep(0.8)
            async with ctx.typing():
                await asyncio.sleep(0.5)
        await send_as_agent(ctx.channel, agent_id, msg)


# ── 유나 제안 시스템 ─────────────────────────────────

@bot.command(name="분석")
async def cmd_analyze(ctx):
    """유나가 현재 상황 분석 + 새 에이전트 제안 여부 판단"""
    mgr_id = "agent-mgr-001"
    runtime.activate_agent(mgr_id)

    # 최근 대화 로그 수집
    conn = db.get_conn()
    recent_logs = conn.execute(
        "SELECT channel, speaker, message FROM conversations ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    conn.close()

    log_text = "\n".join([
        f"[{r['channel']}] {r['speaker']}: {r['message']}"
        for r in reversed(recent_logs)
    ])

    from src.core.prompts.en.commands.analyze_logs import analyze_logs_prompt
    analysis_prompt = analyze_logs_prompt(log_text=log_text)

    async with ctx.typing():
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(mgr_id, "mgr-dashboard", analysis_prompt)
        )

    for msg in responses:
        await send_as_agent(ctx.channel, mgr_id, msg)
        await asyncio.sleep(0.5)


# ── 개발 요청 명령어 ──────────────────────────────────

@bot.command(name="개발")
async def cmd_dev_request(ctx, *, request: str):
    """개발 요청 — !개발 그룹채팅에서 전원 응답하게 수정해줘"""
    mgr_id = "agent-mgr-001"

    await send_as_agent(ctx.channel, mgr_id, f"개발 요청 접수할게")
    await yuna_dev_request(ctx.channel, request, get_user_name())
