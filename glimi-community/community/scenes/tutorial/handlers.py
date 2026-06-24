"""
Tutorial scene — Phase 2 채널 세팅 액션들 (transport-neutral, adapter-driven).

기존 src/bot/mgr_system.py 의 `_trigger_tutorial_phase2` / `_tutorial_setup_channels`
를 scene 폴더로 이전 (Phase 4.5: discord guild → ChannelAdapter).

각 함수는 `channels: ChannelAdapter` 를 받는다 (web=WebChannelAdapter / discord=Discord
Adapter). discord.utils.get → channels.find_channel/list_channels, create_tutorial_channel
→ channels.ensure_channel, 카테고리 재정렬 → channels.reorder_categories() (web no-op).
Phase/seed/prompt 로직은 verbatim 유지.

`import discord` / `community.bot.*` top-level import 절대 금지 (web python 엔 discord 미설치).
"""
from __future__ import annotations

import asyncio
import json as _json

from community import db, log_writer
from community.core.channels import MGR_CHANNEL, CREATOR_CHANNEL, MGR_ID
from community.core.profile import load_profile
from community.core.runtime import runtime
from community.scenes.tutorial.scene import scene

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
        log_writer.system(f"✓ creator lazy 시드 등록: {CREATOR_ID}")
        return True
    except Exception as e:
        log_writer.system(f"❌ creator 시드 로드 실패: {type(e).__name__}: {e}")
        return False


def _load_owner_fields() -> dict:
    """users 테이블에서 오너 표시 필드 추출 (이름/별명/나이/성별/말투)."""
    conn = db.get_conn()
    user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    conn.close()
    user = dict(user) if user else {}
    pers = user.get("personality")
    if isinstance(pers, str):
        try:
            pers = _json.loads(pers)
        except Exception:
            pers = {}
    pers = pers or {}
    speech_raw = user.get("speech")
    speech_info = ""
    if speech_raw:
        try:
            s = _json.loads(speech_raw) if isinstance(speech_raw, str) else speech_raw
            speech_info = s.get("style", "")
        except Exception:
            pass
    owner_name = user.get("name", "?")
    owner_nickname = pers.get("nickname", "")
    return {
        "name": owner_name,
        "nickname": owner_nickname,
        "age": user.get("age", "?"),
        "gender": pers.get("gender", ""),
        "speech": speech_info,
        "call_name": owner_nickname if owner_nickname else owner_name,
    }


def _build_creator_greeting_prompt(creator_name: str, owner: dict, older: bool,
                                   with_speech: bool = False) -> str:
    """크리에이터(하나) 첫 인사 프롬프트 — 본문 verbatim (setup/force 공용)."""
    speech_line = ""
    if with_speech and owner.get("speech"):
        speech_line = f"유나랑은 {owner['speech']}로 대화하기로 했대.\n"
    call_name = owner["call_name"]
    return (
        f"[상황] 유나가 너를 소개해줬어. 오너 정보: 이름={owner['name']}, "
        f"별명={owner['nickname'] or '없음'}, 나이={owner['age']}, 성별={owner['gender']}\n"
        f"{speech_line}"
        f"[지시] 너({creator_name})는 크리에이터야. {call_name}에게 처음 인사하는 상황이야.\n"
        f"[포함할 내용]\n"
        f"- 자기소개 (이름, 성격, 역할: 새 친구의 외모/성격/배경을 디자인해서 만들어주는 크리에이터)\n"
        f"- 자연스럽게 아이스브레이킹 (가벼운 대화)\n"
        f"- 어떻게 불러줄지 물어봐 (이름/별명)\n"
        f"- 존댓말/반말 선호도 물어봐\n"
        f"- 새 친구를 만들 준비가 되면 말해달라고 (급하지 않게)\n"
        f"[규칙]\n"
        f"- '오너' '오너분' 쓰지 마. {call_name} 이름이나 별명으로 불러.\n"
        f"- {call_name}은(는) {owner['age']}살. "
        f"{'너보다 연상이니까 존댓말로 시작.' if older else '나이 비슷하거나 모르니까 일단 존댓말.'}\n"
        f"- 질문 한 번에 하나씩.\n"
        f"- 너의 나이는 굳이 말하지 마.\n"
        f"[스타일] 카톡처럼 짧은 메시지 여러 개로. 자연스럽고 친근하게."
    )


def _older_than_creator(owner_age, creator_age) -> bool:
    if str(owner_age).isdigit() and str(creator_age).isdigit():
        return int(owner_age) > int(creator_age)
    return True


async def force_hana_greeting_if_missing(channels) -> bool:
    """복구 헬퍼 — phase 가 channels_done/complete 인데 creator DM(dm-<하나>) 에 creator
    발화가 0 건이면 Hana 첫 인사가 누락된 상태. setup 의 Hana 인사 부분만 강제 실행.

    회귀 케이스: 첫 부팅 시 Hana 호출 중 prompt 빌더에서 NameError 등으로 abort →
    phase 는 channels_done 으로 진척했지만 실제 Hana 메시지 없음 → 오너가 영원히 대기.

    반환: 복구 실행했으면 True.
    """
    creator_ch = await channels.find_channel(CREATOR_CHANNEL)
    if not creator_ch:
        return False
    creator_msgs = db.get_recent_messages(CREATOR_CHANNEL, limit=1)
    has_creator_msg = bool(creator_msgs) and any(
        m.get("speaker") == CREATOR_ID for m in creator_msgs
    )
    if has_creator_msg:
        return False
    log_writer.system(
        "[recovery] creator DM 에 Hana 발화 0건 — 첫 인사 누락 복구 시작"
    )
    _ensure_creator_seeded()
    runtime.activate_agent(CREATOR_ID)

    creator_profile = load_profile(CREATOR_ID)
    creator_name = creator_profile["name"] if creator_profile else "하나"
    owner = _load_owner_fields()
    creator_age = creator_profile.get("age", "?") if creator_profile else "?"
    older = _older_than_creator(owner["age"], creator_age)
    creator_prompt = _build_creator_greeting_prompt(creator_name, owner, older)

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
        resp = (resp or "").strip()
        if not resp:
            continue
        await channels.send_as_agent(CREATOR_CHANNEL, CREATOR_ID, resp)
        sent += 1
        await asyncio.sleep(1)
    log_writer.system(f"[recovery] Hana 첫 인사 복구 완료 — {sent}건 발송")
    if scene.current_phase() in ("channels_setup",):
        scene.set_phase("channels_done")
    return True


async def trigger_phase2(channels):
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
            await setup_channels(channels)
        except Exception as e:
            log_writer.system(f"❌ [sup:tutorial] 오류: {type(e).__name__}: {e}")

    asyncio.get_event_loop().create_task(_safe_setup())


async def setup_channels(channels):
    """Phase 2 본체 — 크리에이터(하나) DM 생성, 유나 안내, 하나 인사 (adapter-driven)."""
    current = scene.current_phase()
    if current in ("channels_done", "complete"):
        return
    log_writer.system("[sup:tutorial] 시작: 채널 생성 + 크리에이터 소개")

    await asyncio.sleep(2)

    # 크리에이터(하나) 이름 — 유나가 이름으로 자연스럽게 안내하도록.
    creator_profile = load_profile(CREATOR_ID)
    creator_name = creator_profile["name"] if creator_profile else "하나"

    # 1. 유나 안내 (mgr DM 에서) — 크리에이터를 '이름'으로 자연스럽게 소개.
    mgr_ch = await channels.find_channel(MGR_CHANNEL)
    if mgr_ch:
        prompt = (
            "[상황] 오너 프로필 수집이 끝났어. 이제 튜토리얼 다음 단계로 넘어가는 순간.\n"
            "[지시] 아래 흐름을 순서대로 — 네 말투로 자연스럽게 풀어서 전달:\n"
            f"  1. 이제 새 친구를 만들어줄 {creator_name}을(를) 소개해줄게.\n"
            f"  2. {creator_name}이(가) 곧 따로 인사할 거야. {creator_name}한테 어떤 친구 "
            "원하는지 얘기하면 같이 만들어줘.\n"
            "[중요]\n"
            "  - '채널'/'시스템 로그' 같은 용어 쓰지 말고, 사람 이름으로 자연스럽게.\n"
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
            resp = (resp or "").strip()
            if not resp:
                continue
            await channels.send_as_agent(MGR_CHANNEL, MGR_ID, resp)
            await asyncio.sleep(1)

    await asyncio.sleep(3)

    # 2. 크리에이터(하나) lazy 시드 — 이 phase 에 '새로 등장'하는 것처럼
    _ensure_creator_seeded()

    # 3. 크리에이터(하나) DM 채널 생성 (dm-<하나>)
    try:
        creator_ch = await channels.ensure_channel(
            CREATOR_CHANNEL, participants=[CREATOR_ID]
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
    owner = _load_owner_fields()
    creator_age = creator_profile.get("age", "?") if creator_profile else "?"
    older = _older_than_creator(owner["age"], creator_age)
    creator_prompt = _build_creator_greeting_prompt(
        creator_name, owner, older, with_speech=True
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
        resp = (resp or "").strip()
        if not resp:
            continue
        await channels.send_as_agent(CREATOR_CHANNEL, CREATOR_ID, resp)
        sent_any = True
        await asyncio.sleep(1)
    if not sent_any:
        log_writer.system(f"⚠ {CREATOR_CHANNEL}에 인사 메시지 0건 — 생성 응답 비어있음")

    # 카테고리 순서 정렬 (discord categories; web no-op)
    await channels.reorder_categories()

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
