"""
Tutorial scene — Phase 2 채널 세팅 액션들.

기존 src/bot/mgr_system.py 의 `_trigger_tutorial_phase2` / `_tutorial_setup_channels`
를 scene 폴더로 이전. 호출부는 동일 — import 경로만 바뀜.
"""
from __future__ import annotations

import asyncio
import json as _json
import re as _re

import discord

from src import db, log_writer
from src.bot import MGR_CHANNEL, MGR_SYSTEM_LOG, CREATOR_CHANNEL, MGR_ID
from src.bot.core import (
    create_tutorial_channel,
    send_as_agent,
    _split_for_chat,
)
from src.core.profile import load_profile
from src.core.runtime import runtime
from src.scenes.tutorial.scene import scene

CREATOR_ID = "agent-creator-001"


def _ensure_creator_seeded() -> bool:
    """크리에이터(하나) 에이전트가 DB 에 없으면 시드에서 등록.
    튜토리얼 channels_setup phase 에 lazy 호출 — 초기 상태에선 mgr 만 존재 → 오너 시점에
    '하나가 튜토리얼 중 새로 생긴 것처럼' 보이게.
    반환: 실제로 등록됐으면 True, 이미 있어서 skip 했거나 실패면 False."""
    from pathlib import Path
    if db.get_agent(CREATOR_ID):
        return False
    seed_path = Path(__file__).resolve().parents[3] / "assets" / "seed_agents.json"
    if not seed_path.exists():
        log_writer.system(f"❌ creator 시드 파일 없음: {seed_path}")
        return False
    try:
        with open(seed_path, "r", encoding="utf-8") as f:
            seeds = _json.load(f)
        creator_seed = next((a for a in seeds if a.get("id") == CREATOR_ID), None)
        if not creator_seed:
            log_writer.system(f"❌ creator 시드 엔트리 없음 in {seed_path.name}")
            return False
        db.save_agent_profile(creator_seed)
        # 채널 ↔ 에이전트 매핑 갱신 (봇 startup 의 _build_channel_maps 이후 추가된 agent)
        try:
            from src.bot import CHANNEL_AGENT_MAP, AGENT_CHANNEL_MAP
            CHANNEL_AGENT_MAP[CREATOR_CHANNEL] = CREATOR_ID
            AGENT_CHANNEL_MAP[CREATOR_ID] = CREATOR_CHANNEL
        except Exception:
            pass
        log_writer.system(f"✓ creator lazy 시드 등록: {CREATOR_ID}")
        return True
    except Exception as e:
        log_writer.system(f"❌ creator 시드 로드 실패: {type(e).__name__}: {e}")
        return False


async def force_hana_greeting_if_missing(guild) -> bool:
    """복구 헬퍼 — phase 가 channels_done/complete 인데 mgr-creator 에 creator 발화가
    0 건이면 Hana 첫 인사가 누락된 상태. setup_channels 의 Hana 인사 부분만 강제 실행.

    회귀 케이스: 봇 첫 부팅 시 Hana 호출 중 prompt 빌더에서 NameError 등으로 abort →
    phase 는 channels_done 으로 진척했지만 실제 Hana 메시지 없음 → 오너가 영원히 대기.

    반환: 복구 실행했으면 True.
    """
    creator_ch = discord.utils.get(guild.text_channels, name=CREATOR_CHANNEL)
    if not creator_ch:
        return False
    creator_msgs = db.get_recent_messages(CREATOR_CHANNEL, limit=1)
    has_creator_msg = bool(creator_msgs) and any(
        m.get("speaker") == CREATOR_ID for m in creator_msgs
    )
    if has_creator_msg:
        return False
    log_writer.system(
        "[recovery] mgr-creator 에 Hana 발화 0건 — 첫 인사 누락 복구 시작"
    )
    _ensure_creator_seeded()
    runtime.activate_agent(CREATOR_ID)

    creator_profile = load_profile(CREATOR_ID)
    creator_name = creator_profile["name"] if creator_profile else "하나"
    conn = db.get_conn()
    user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    conn.close()
    user = dict(user) if user else {}
    owner_name = user.get("name", "?")
    pers = user.get("personality")
    if isinstance(pers, str):
        try:
            pers = _json.loads(pers)
        except Exception:
            pers = {}
    pers = pers or {}
    owner_nickname = pers.get("nickname", "")
    owner_age = user.get("age", "?")
    owner_gender = pers.get("gender", "")
    call_name = owner_nickname if owner_nickname else owner_name

    creator_age = creator_profile.get("age", "?") if creator_profile else "?"
    older = (
        int(owner_age) > int(creator_age)
        if str(owner_age).isdigit() and str(creator_age).isdigit()
        else True
    )
    creator_prompt = (
        f"[상황] 유나가 너를 소개해줬어. 오너 정보: 이름={owner_name}, "
        f"별명={owner_nickname or '없음'}, 나이={owner_age}, 성별={owner_gender}\n"
        f"[지시] 너({creator_name})는 크리에이터야. {call_name}에게 처음 인사하는 상황이야.\n"
        f"[포함할 내용]\n"
        f"- 자기소개 (이름, 성격, 역할: 새 친구의 외모/성격/배경을 디자인해서 만들어주는 크리에이터)\n"
        f"- 자연스럽게 아이스브레이킹 (가벼운 대화)\n"
        f"- 어떻게 불러줄지 물어봐 (이름/별명)\n"
        f"- 존댓말/반말 선호도 물어봐\n"
        f"- 새 친구를 만들 준비가 되면 말해달라고 (급하지 않게)\n"
        f"[규칙]\n"
        f"- '오너' '오너분' 쓰지 마. {call_name} 이름이나 별명으로 불러.\n"
        f"- {call_name}은(는) {owner_age}살. "
        f"{'너보다 연상이니까 존댓말로 시작.' if older else '나이 비슷하거나 모르니까 일단 존댓말.'}\n"
        f"- 질문 한 번에 하나씩.\n"
        f"- 너의 나이는 굳이 말하지 마.\n"
        f"[스타일] 카톡처럼 짧은 메시지 여러 개로. 자연스럽고 친근하게."
    )
    loop = asyncio.get_event_loop()
    try:
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(
                CREATOR_ID, CREATOR_CHANNEL, creator_prompt, log_user_message=False
            ),
        )
    except Exception as e:
        log_writer.system(f"[recovery] Hana 응답 생성 실패: {type(e).__name__}: {e}")
        return False
    sent = 0
    for resp in responses or []:
        resp = resp.strip()
        if not resp:
            continue
        for part in _split_for_chat(resp):
            await send_as_agent(creator_ch, CREATOR_ID, part)
            sent += 1
            await asyncio.sleep(1)
    log_writer.system(f"[recovery] Hana 첫 인사 복구 완료 — {sent}건 발송")
    # phase 가 아직 setup 이면 done 으로 진척
    if scene.current_phase() in ("channels_setup",):
        scene.set_phase("channels_done")
    return True


async def trigger_phase2(guild):
    """Phase 2 트리거 — scene의 phase를 channels_setup으로 전환하고
    채널 생성/크리에이터 소개를 비동기 실행."""
    current = scene.current_phase()
    if current in ("channels_setup", "channels_done", "complete"):
        log_writer.system(f"[sup:tutorial] 이미 진행/완료 (phase={current}) — 스킵")
        return
    scene.set_phase("channels_setup")
    runtime.refresh_agent(MGR_ID)  # phase 바뀌었으니 유나 프롬프트 갱신
    log_writer.system("[sup:tutorial] 트리거됨")

    async def _safe_setup():
        try:
            await setup_channels(guild)
        except Exception as e:
            log_writer.system(f"❌ [sup:tutorial] 오류: {type(e).__name__}: {e}")

    asyncio.get_event_loop().create_task(_safe_setup())


async def setup_channels(guild):
    """Phase 2 본체 — mgr-system-log + mgr-creator 생성, 유나 안내, 하나 인사."""
    current = scene.current_phase()
    if current in ("channels_done", "complete"):
        return
    log_writer.system("[sup:tutorial] 시작: 채널 생성 + 크리에이터 소개")

    await asyncio.sleep(2)

    # 1. mgr-system-log 생성 + 유나 안내 (mgr-dashboard에서)
    try:
        log_ch = await create_tutorial_channel(
            guild, MGR_SYSTEM_LOG, participants=[MGR_ID]
        )
    except Exception as e:
        log_writer.system(
            f"❌ Phase 2 중단: {MGR_SYSTEM_LOG} 생성 실패 ({type(e).__name__}: {e})"
        )
        return
    if not log_ch:
        log_writer.system(f"❌ Phase 2 중단: {MGR_SYSTEM_LOG} 생성 결과 없음")
        return

    mgr_ch = discord.utils.get(guild.text_channels, name=MGR_CHANNEL)
    if mgr_ch:
        # 고정 순서 템플릿 — LLM이 순서 섞거나 채널 설명 혼동하는 것 방지.
        # Yuna가 2건 응답한 것처럼 보이게 카톡 스타일로 나눠 전송.
        prompt = (
            "[상황] 오너 프로필 수집이 끝났어. 이제 튜토리얼 다음 단계로 넘어가는 순간.\n"
            "[지시] 아래 흐름을 순서대로 — 네 말투로 자연스럽게 풀어서 전달:\n"
            f"  1. 방금 #{MGR_SYSTEM_LOG} 채널이 생겼어. 그건 시스템 로그가 올라오는 곳 "
            "(멤버 활동, 상태 변화 등 자동 기록).\n"
            f"  2. 그리고 #{CREATOR_CHANNEL} 채널도 생겼는데, 거기에 곧 크리에이터(하나)가 와서 "
            "새 친구 만드는 걸 도와줄 거야.\n"
            "  3. 하나가 인사하면 #mgr-creator 가서 어떤 친구 원하는지 얘기해봐.\n"
            "[중요]\n"
            "  - 두 채널을 혼동하지 마. #mgr-system-log 는 로그 채널, #mgr-creator 는 친구 생성 채널.\n"
            "  - 채널명은 항상 #채널명 형식 (볼드/평문 섞지 마).\n"
            "  - 같은 안내 반복하지 마. 한 번만 깔끔하게.\n"
            "[스타일] 카톡처럼 3~5개 짧은 메시지로. 친근하게.\n"
            "[금지] `<tools>` 블록 쓰지 마 (지금은 안내 텍스트만)."
        )
        loop = asyncio.get_event_loop()
        responses = await loop.run_in_executor(
            None,
            lambda: runtime.generate_response(
                MGR_ID, MGR_CHANNEL, prompt, log_user_message=False
            ),
        )
        for resp in responses:
            resp = resp.strip()
            if not resp:
                continue
            for part in _split_for_chat(resp):
                await send_as_agent(mgr_ch, MGR_ID, part)
                await asyncio.sleep(1)

    await asyncio.sleep(3)

    # 2. 크리에이터(하나) lazy 시드 — 이 phase 에 '새로 등장'하는 것처럼
    _ensure_creator_seeded()

    # 3. mgr-creator 생성
    try:
        creator_ch = await create_tutorial_channel(
            guild, CREATOR_CHANNEL, participants=[CREATOR_ID]
        )
    except Exception as e:
        log_writer.system(
            f"❌ Phase 2 중단: {CREATOR_CHANNEL} 생성 실패 ({type(e).__name__}: {e})"
        )
        return
    if not creator_ch:
        log_writer.system(f"❌ Phase 2 중단: {CREATOR_CHANNEL} 생성 결과 없음")
        return

    await asyncio.sleep(2)

    # 4. 크리에이터(하나) 인사
    runtime.activate_agent(CREATOR_ID)
    creator_profile = load_profile(CREATOR_ID)
    creator_name = creator_profile["name"] if creator_profile else "하나"

    conn = db.get_conn()
    user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    conn.close()
    user = dict(user) if user else {}
    owner_name = user.get("name", "?")
    pers = user.get("personality")
    if isinstance(pers, str):
        try:
            pers = _json.loads(pers)
        except Exception:
            pers = {}
    pers = pers or {}
    owner_nickname = pers.get("nickname", "")
    owner_age = user.get("age", "?")
    owner_gender = pers.get("gender", "")
    call_name = owner_nickname if owner_nickname else owner_name

    speech_raw = user.get("speech")
    speech_info = ""
    if speech_raw:
        try:
            s = _json.loads(speech_raw) if isinstance(speech_raw, str) else speech_raw
            speech_info = s.get("style", "")
        except Exception:
            pass

    creator_age = creator_profile.get("age", "?") if creator_profile else "?"
    older = (
        int(owner_age) > int(creator_age)
        if str(owner_age).isdigit() and str(creator_age).isdigit()
        else True
    )

    creator_prompt = (
        f"[상황] 유나가 너를 소개해줬어. 오너 정보: 이름={owner_name}, "
        f"별명={owner_nickname or '없음'}, 나이={owner_age}, 성별={owner_gender}\n"
        f"{'유나랑은 ' + speech_info + '로 대화하기로 했대.' if speech_info else ''}\n"
        f"[지시] 너({creator_name})는 크리에이터야. {call_name}에게 처음 인사하는 상황이야.\n"
        f"[포함할 내용]\n"
        f"- 자기소개 (이름, 성격, 역할: 새 친구의 외모/성격/배경을 디자인해서 만들어주는 크리에이터)\n"
        f"- 자연스럽게 아이스브레이킹 (가벼운 대화)\n"
        f"- 어떻게 불러줄지 물어봐 (이름/별명)\n"
        f"- 존댓말/반말 선호도 물어봐\n"
        f"- 새 친구를 만들 준비가 되면 말해달라고 (급하지 않게)\n"
        f"[규칙]\n"
        f"- '오너' '오너분' 쓰지 마. {call_name} 이름이나 별명으로 불러.\n"
        f"- {call_name}은(는) {owner_age}살. "
        f"{'너보다 연상이니까 존댓말로 시작.' if older else '나이 비슷하거나 모르니까 일단 존댓말.'}\n"
        f"- 질문 한 번에 하나씩.\n"
        f"- 너의 나이는 굳이 말하지 마.\n"
        f"[스타일] 카톡처럼 짧은 메시지 여러 개로. 자연스럽고 친근하게. 로봇 같은 정형화된 말투 금지."
    )

    loop = asyncio.get_event_loop()
    responses = await loop.run_in_executor(
        None,
        lambda: runtime.generate_response(
            CREATOR_ID, CREATOR_CHANNEL, creator_prompt, log_user_message=False
        ),
    )
    sent_any = False
    for resp in responses:
        resp = resp.strip()
        if not resp:
            continue
        for part in _split_for_chat(resp):
            await send_as_agent(creator_ch, CREATOR_ID, part)
            sent_any = True
            await asyncio.sleep(1)
    if not sent_any:
        log_writer.system(f"⚠ {CREATOR_CHANNEL}에 인사 메시지 0건 — 생성 응답 비어있음")

    # 카테고리 순서 정렬
    from src.core.sync import CATEGORY_ORDER
    for i, cat_name in enumerate(CATEGORY_ORDER):
        cat = discord.utils.get(guild.categories, name=cat_name)
        if cat:
            try:
                await cat.edit(position=i)
            except Exception:
                pass

    scene.set_phase("channels_done")
    runtime.refresh_agent(MGR_ID)  # Phase 2 완료 → 유나 프롬프트 갱신
    log_writer.system(
        "튜토리얼 Phase 2 완료: 시스템 채널 + 크리에이터 인사 (최종 완료 대기)"
    )


async def complete_tutorial():
    """최종 완료 — tool handler에서 호출."""
    scene.set_phase("complete")
    runtime.refresh_agent(MGR_ID)
    log_writer.mark_tutorial_complete()
    log_writer.system("튜토리얼 최종 완료")
