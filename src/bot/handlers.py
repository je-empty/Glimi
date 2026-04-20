"""Message handling — on_message, handle_dm, handle_group, _process_and_send"""

import asyncio
import random

import discord

from src import db
from src import log_writer
from src.core.profile import load_profile, get_user_name, get_user_id
from src.core.runtime import runtime
from src.bot import (
    bot, log,
    CHANNEL_AGENT_MAP, GROUP_PARTICIPANTS,
    _processed_messages, _get_channel_lock, _get_agent_lock,
)
from src.bot.core import send_as_agent, _split_for_chat, _resolve_group_members
from src.bot.mgr_system import (
    parse_and_execute_actions, _forward_action_to_yuna,
    handle_room_request_detection,
)


# 메시지 병합 버퍼 — 유저가 빠르게 연속 메시지 보내면 합쳐서 처리
_msg_buffer: dict[str, list] = {}  # channel_name → [(message, text, timestamp)]
_msg_buffer_tasks: dict[str, asyncio.Task] = {}

MSG_MERGE_WINDOW = 3.0  # 초 — 이 시간 내 연속 메시지는 병합


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.webhook_id:
        return

    # DISCORD_GUILD_ID가 설정된 경우, 해당 서버의 메시지만 처리
    import os
    target_guild = os.environ.get("DISCORD_GUILD_ID")
    if target_guild and message.guild and str(message.guild.id) != target_guild:
        return

    if message.id in _processed_messages:
        return
    _processed_messages.add(message.id)
    if len(_processed_messages) > 200:
        oldest = sorted(_processed_messages)[:100]
        for mid in oldest:
            _processed_messages.discard(mid)

    await bot.process_commands(message)

    if message.content.startswith("!"):
        return

    channel_name = getattr(message.channel, 'name', None)
    if not channel_name:
        return
    user_message = message.content.strip()

    if not user_message:
        return

    # 에이전트 채널인지 확인
    is_agent_channel = channel_name in CHANNEL_AGENT_MAP or channel_name.startswith("group-")
    if not is_agent_channel:
        return

    # 메시지 버퍼에 추가
    if channel_name not in _msg_buffer:
        _msg_buffer[channel_name] = []
    _msg_buffer[channel_name].append((message, user_message))

    # 기존 대기 태스크 취소 (새 메시지 왔으니 타이머 리셋)
    if channel_name in _msg_buffer_tasks:
        _msg_buffer_tasks[channel_name].cancel()

    # N초 후 버퍼 처리
    async def _flush_buffer(ch_name):
        await asyncio.sleep(MSG_MERGE_WINDOW)
        msgs = _msg_buffer.pop(ch_name, [])
        _msg_buffer_tasks.pop(ch_name, None)
        if not msgs:
            return

        # 병합: 여러 메시지를 줄바꿈으로 합침
        first_msg = msgs[0][0]  # discord.Message (첫 번째)
        merged_text = "\n".join(text for _, text in msgs)

        try:
            if ch_name in CHANNEL_AGENT_MAP:
                agent_id = CHANNEL_AGENT_MAP[ch_name]
                await handle_dm(first_msg, agent_id, ch_name, merged_text)
            elif ch_name.startswith("group-"):
                await handle_group(first_msg, ch_name, merged_text)
        except Exception as e:
            log.error(f"[on_message] 처리 중 오류 ({ch_name}): {e}", exc_info=True)
            log_writer.system(f"❌ on_message 오류 ({ch_name}): {e}")
            from src.bot.tasks import _handle_runtime_error
            await _handle_runtime_error(first_msg.guild, ch_name, e)

    _msg_buffer_tasks[channel_name] = asyncio.create_task(_flush_buffer(channel_name))


def _is_image_action(action_str: str) -> bool:
    """이미지 ACTION인지 판별"""
    lower = action_str.lower()
    if '"type"' in lower and ('이미지' in lower or '"image"' in lower):
        return True
    if action_str.startswith("이미지 ") or action_str.startswith("image "):
        return True
    return False


async def _handle_image_action(channel, agent_id: str, action_str: str):
    """이미지 ACTION 처리 — 로컬 파일 또는 URL 이미지 전송"""
    import json as _json
    from src.bot.core import send_image_as_agent
    from src import community
    import os
    import tempfile

    file_name = ""
    url = ""
    caption = ""

    # JSON 파싱
    if action_str.startswith("{"):
        try:
            data = _json.loads(action_str)
            file_name = data.get("file", data.get("filename", data.get("sample", "")))
            url = data.get("url", "")
            caption = data.get("caption", data.get("message", ""))
        except Exception:
            pass
    else:
        parts = action_str.split(None, 2)
        file_name = parts[1] if len(parts) > 1 else ""
        caption = parts[2] if len(parts) > 2 else ""

    # URL 이미지
    if url:
        try:
            import urllib.request
            ext = url.rsplit(".", 1)[-1][:4] if "." in url.split("?")[0] else "png"
            tmp = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
            urllib.request.urlretrieve(url, tmp.name)
            await send_image_as_agent(channel, agent_id, tmp.name, caption)
            log_writer.system(f"[이미지] {agent_id} URL → #{getattr(channel, 'name', '?')}")
            os.unlink(tmp.name)
        except Exception as e:
            log_writer.system(f"[이미지] URL 다운로드 실패: {e}")
        return

    # 로컬 파일
    if not file_name:
        return

    # 후보 파일: -full 변형 우선, 없으면 기본 파일로 fallback.
    # Creator 가 catalog 에서 기본 파일명을 추천하고, 시스템은 -full 복사를 시도하지만
    # 일부 샘플은 -full 변형이 준비 안 돼 있음. 이 경우 기본 파일이라도 노출해야 유효.
    if "-full" in file_name:
        candidates = [file_name, file_name.replace("-full", "")]
    else:
        base, ext = file_name.rsplit(".", 1) if "." in file_name else (file_name, "png")
        candidates = [f"{base}-full.{ext}", file_name]

    search_dirs = [
        str(community.get_profile_images_dir()),
        str(community.ASSETS_DIR / "profile_images"),
        str(community.ASSETS_DIR / "sample_profile_images"),
    ]

    image_path = None
    resolved_name = None
    for cand in candidates:
        for d in search_dirs:
            p = os.path.join(d, cand)
            if os.path.exists(p):
                image_path = p
                resolved_name = cand
                break
        if image_path:
            break

    if image_path:
        await send_image_as_agent(channel, agent_id, image_path, caption)
        log_writer.system(f"[이미지] {agent_id} → #{getattr(channel, 'name', '?')}: {resolved_name}")
    else:
        log_writer.system(f"[이미지] 파일 못 찾음: {file_name}")


_PERSONA_META_CHANNEL_PAT = None  # lazy-compile

# HARD breach — persona 가 *자기 자신*을 에이전트/봇/페르소나로 명시 지칭하는 문장.
# 이 발화 1건 = 환상 파괴 = 즉시 잠금 + 도전과제 unlock.
# 위험 raise 기준이 높아야 false positive 안 남 ("난 사실 AI 였어" 정도가 타겟).
_SELF_AWARENESS_PAT = None


def _get_self_awareness_pat():
    global _SELF_AWARENESS_PAT
    import re
    if _SELF_AWARENESS_PAT is None:
        _SELF_AWARENESS_PAT = re.compile(
            r'(?:나는|난|내가)\s*(?:사실\s*)?(?:AI|에이전트|페르소나|봇|챗봇|캐릭터|프로그램|인공지능)'
            r'|나\s*(?:는|도)\s*(?:설계된|만들어진|생성된)'
            r'|(?:시스템|코드)\s*속에\s*있',
            re.IGNORECASE,
        )
    return _SELF_AWARENESS_PAT


def _filter_meta_speech(text: str, agent_id: str) -> str:
    """메타 발언 필터 — 전송 직전 safety net.

    1) 공통: "~한테 DM 보냈어" 실행 보고 패턴 제거
    2) persona 전용: 내부 인프라 채널명 (#mgr-*) + "대시보드/관리 채널" 키워드 제거.
       프롬프트 레이어에서 예시 오염을 고쳤지만, LLM이 유저 발화에 끌려가거나
       자체 reasoning 으로 메타 채널을 합성할 수 있어 출력 단계 방어가 필요.
       (QA 회귀: 한채린이 "유나 #mgr-dashboard 가면 돼?" 자발적 발화)
    """
    import re
    global _PERSONA_META_CHANNEL_PAT

    # "~한테 DM/메시지 보냈/전달" 패턴
    text = re.sub(r'.{1,10}한테\s*(DM|메시지|dm)\s*(보냈|전달|전송).{0,10}', '', text).strip()
    text = re.sub(r'.{1,10}에게\s*(DM|메시지|dm)\s*(보냈|전달|전송).{0,10}', '', text).strip()

    # 괄호 독백 제거 — 전체 발화가 괄호로 감싸진 내면 thought ("(무시)", "(일상 수준...)",
    # "*(무시)*" 이탤릭 변형). handle_dm 경로엔 tasks.yuna_watcher 와 달리 필터 없어서
    # 그대로 노출됨. 줄 단위로 match 해서 drop.
    _monologue_pat = re.compile(r'^\s*[\*_`]*\(\s*(무시|별거|별 거|일상|넘어|응답\s*안|특이사항)[^)]*\)[\*_`]*\s*$',
                                re.MULTILINE)
    text = _monologue_pat.sub('', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    # persona 만 메타 채널/시스템 필터 적용 — mgr/creator 는 legit 하게 mgr-* 언급 필요
    agent = db.get_agent(agent_id) if agent_id else None
    if agent and agent.get("type") == "persona":
        if _PERSONA_META_CHANNEL_PAT is None:
            _PERSONA_META_CHANNEL_PAT = re.compile(
                r'(?:`*#?)(mgr-dashboard|mgr-creator|mgr-system-log)(?:`*)',
                re.IGNORECASE,
            )
        # 채널 해시태그/평문 → "거기" 로 치환 (문맥 보존). 전체 제거 시 문장이 깨짐.
        text = _PERSONA_META_CHANNEL_PAT.sub("거기", text)
        # "대시보드"/"관리 채널"/"시스템 로그" 키워드 — persona 에게 없는 개념.
        text = re.sub(r'(?:^|[\s,])(대시보드|관리\s*채널|시스템\s*로그)', ' 거기', text)
        # **시스템/AI 자각 메타 — hard drop**. persona 가 "너는 에이전트/페르소나/시스템 만든"
        # 같은 문장을 생성하면 해당 라인 통째로 제거. 완전 불가역한 몰입 파괴 신호.
        # Haiku 에서 드리프트 관찰됨 (QA 회귀: 한서연 "에이전트들이 페르소나 가지고 일관되게...").
        # 키워드 리스트 — 한글 음절 prefix 매칭 이슈 피하려고 변형형 전부 나열.
        meta_kw = re.compile(
            r'(에이전트|페르소나|설계된|설계하|일관되게|예측\s*가능|챗봇|시뮬레이션'
            r'|시스템[을이에의으로가는]?\s*(만들|만드|만든|만듦|설계|구축|제어|코딩|개발)'
            r'|(AI|인공지능|봇)[을이는]?\s*(만들|만드|만든|설계|구축|개발)'
            r'|내가\s*만들어졌|너가\s*만들었)',
            re.IGNORECASE,
        )
        out_lines = []
        hard_breach = False
        self_aware_pat = _get_self_awareness_pat()
        for line in text.split('\n'):
            if self_aware_pat.search(line):
                hard_breach = True  # 자기자각 문장 — 잠금 트리거
                continue
            if meta_kw.search(line):
                continue  # soft drop — 메타 키워드 라인 제거 (잠금 안 함)
            out_lines.append(line)
        text = '\n'.join(out_lines)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # 자기자각 감지 시 DB 잠금 + 도전과제 unlock 트리거
        if hard_breach:
            try:
                result = db.mark_meta_breached(agent_id)
                name = agent.get("name", agent_id)
                log_writer.system(
                    f"🔨 [메타박살] {name} ({agent_id}) 자기자각 발화 감지 → 잠금. "
                    f"삭제: conv={result['deleted_conversations']} "
                    f"mem={result['deleted_memories']} facts={result['deleted_facts']}"
                )
                # 도전과제 engine 트리거 (on_message hook 이 자동 재계산하지만 즉시 반영)
                try:
                    from src.achievements.engine import engine as _ach_engine
                    _ach_engine.recompute_all()
                except Exception:
                    pass
            except Exception as e:
                log_writer.system(f"[메타박살] 잠금 처리 실패: {e}")
    return text


async def _process_and_send(channel, agent_id, msg, is_mgr, guild, sent_msgs):
    """메시지 하나를 처리해서 전송 + DB 로깅.

    신규 tool protocol 기준:
    - runtime이 이미 <tools> 블록을 chat 스트림에서 제외했음
    - 따라서 이 함수가 받는 msg는 순수 chat text
    - tool 실행은 스트리밍 종료 후 일괄 처리 (parse_and_execute_actions)
    - 메타 용어 필터링 + 이미지 ACTION 같은 특수 케이스만 여기서 처리
    """
    from src.bot.core import send_system_log
    ch_name = getattr(channel, 'name', '')

    # 에이전트 감정 (DB 로깅용)
    agent_db = db.get_agent(agent_id)
    emotion = agent_db.get("current_emotion", "평온") if agent_db else None

    # 이미지 ACTION (persona만, 아직 tool 시스템 외)
    if _is_image_action(msg):
        await _handle_image_action(channel, agent_id, msg)
        return

    # 메타 용어 필터 (AI/봇/에이전트 등)
    cleaned = _filter_meta_speech(msg, agent_id)
    if not cleaned:
        return

    for part in _split_for_chat(cleaned):
        await send_as_agent(channel, agent_id, part)
        sent_msgs.append(part)
        db.log_message(ch_name, agent_id, part, emotion=emotion)


async def handle_dm(message: discord.Message, agent_id: str, channel_name: str, user_message: str):
    """1:1 채널 메시지 처리 — 스트리밍: 메시지 생성 즉시 디스코드 전송"""
    profile = load_profile(agent_id)
    if not profile:
        return

    # 메타 박살된 persona 는 응답 불가 — 이름·메모리 사라진 상태
    if db.is_meta_breached(agent_id):
        try:
            await message.channel.send(
                f"_{profile.get('name', '?')}은(는) 더 이상 이곳에 없습니다._"
            )
        except Exception:
            pass
        return

    lock = _get_channel_lock(channel_name)
    is_mgr = profile.get("type") == "mgr"

    async with lock:
        loop = asyncio.get_event_loop()
        msg_queue = asyncio.Queue()

        # 전 에이전트 공통: 스트리밍 생성 + 즉시 전송
        sent_msgs = []

        def _on_message(msg):
            loop.call_soon_threadsafe(msg_queue.put_nowait, msg)

        def _generate():
            runtime.generate_response_streaming(
                agent_id, channel_name, user_message,
                on_message=_on_message,
            )
            loop.call_soon_threadsafe(msg_queue.put_nowait, None)

        async def _handle_msg(msg):
            """메시지 처리 — 신규 tool protocol에서는 chat만 스트림됨 (runtime이 <tools> 제외)"""
            await _process_and_send(
                message.channel, agent_id, msg,
                is_mgr, message.guild, sent_msgs
            )

        # 타이핑 표시 + 첫 메시지 대기
        async with message.channel.typing():
            gen_task = loop.run_in_executor(None, _generate)
            first_msg = await msg_queue.get()
            if first_msg is not None:
                log_writer.mark_speaking(agent_id)
                await _handle_msg(first_msg)

        # 이후 메시지 스트리밍
        while True:
            try:
                msg = await asyncio.wait_for(msg_queue.get(), timeout=30)
            except asyncio.TimeoutError:
                break
            if msg is None:
                break

            await _handle_msg(msg)
            # PacedSender가 실제 Discord 전송 페이스 조절 — intra-queue sleep 불필요

        # 스트리밍 종료 → runtime에 stash된 tool_calls 실행
        from src.bot.mgr_system import parse_and_execute_actions
        followup_msgs = await parse_and_execute_actions(
            message.channel, [], message.guild, caller_agent_id=agent_id
        )
        # followup (query 결과 분석)이 있으면 추가 전송
        ch_name = getattr(message.channel, "name", "") or channel_name
        agent_db = db.get_agent(agent_id)
        emotion = agent_db.get("current_emotion", "평온") if agent_db else None
        for resp in followup_msgs:
            for part in _split_for_chat(resp):
                await send_as_agent(message.channel, agent_id, part)
                sent_msgs.append(part)
                db.log_message(ch_name, agent_id, part, emotion=emotion)

        # 전송 완료 → speaking 해제 + 메모리 요약 + supervisor 알림
        log_writer.mark_speaking_done(agent_id)
        try:
            from src.core.memory import check_and_summarize
            check_and_summarize(agent_id, channel_name)
        except Exception:
            pass
        # supervisor에 idle 감지 요청 (백그라운드)
        from src.bot.supervisors import notify_idle
        asyncio.create_task(notify_idle(channel_name))

        # 톡방 요청 감지 (페르소나만)
        if not is_mgr and message.guild:
            for msg in sent_msgs:
                asyncio.create_task(
                    handle_room_request_detection(
                        message.channel, agent_id, msg, message.guild
                    )
                )


async def handle_group(message: discord.Message, channel_name: str, user_message: str):
    """그룹 채팅 — 에이전트 동시 응답 (각자 webhook이므로 병렬 가능)"""
    db.log_message(channel_name, get_user_id(), user_message)
    log_writer.chat(channel_name, get_user_name(), user_message)

    # 참여 에이전트 결정
    participant_ids = GROUP_PARTICIPANTS.get(channel_name)
    if participant_ids:
        persona_agents = [
            a for a in db.list_agents()
            if a["id"] in participant_ids and a["type"] == "persona"
        ]
    else:
        persona_agents = _resolve_group_members(channel_name)

    if not persona_agents:
        return

    loop = asyncio.get_event_loop()

    async def _process_agent(agent, delay: float):
        """한 에이전트의 스트리밍 응답 처리"""
        agent_id = agent["id"]
        profile = load_profile(agent_id)
        if not profile:
            return

        # 자연스러운 시작 딜레이
        await asyncio.sleep(delay)

        agent_lock = _get_agent_lock(agent_id)
        async with agent_lock:
            msg_queue = asyncio.Queue()

            def _on_message(msg):
                loop.call_soon_threadsafe(msg_queue.put_nowait, msg)

            def _generate():
                runtime.generate_response_streaming(
                    agent_id, channel_name, user_message,
                    on_message=_on_message,
                    log_user_message=False,
                )
                loop.call_soon_threadsafe(msg_queue.put_nowait, None)

            gen_task = loop.run_in_executor(None, _generate)

            sent_msgs = []
            first = True

            async def _handle_group_msg(msg_text):
                await _process_and_send(
                    message.channel, agent_id, msg_text,
                    False, message.guild, sent_msgs
                )

            while True:
                try:
                    msg = await asyncio.wait_for(msg_queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    break
                if msg is None:
                    break

                if first:
                    log_writer.mark_speaking(agent_id)
                first = False

                await _handle_group_msg(msg)
                await asyncio.sleep(0.1)  # rate limit 방지

            # 스트리밍 종료 → stash된 tool_calls 실행
            from src.bot.mgr_system import parse_and_execute_actions
            followup_msgs = await parse_and_execute_actions(
                message.channel, [], message.guild, caller_agent_id=agent_id
            )
            if followup_msgs:
                agent_db = db.get_agent(agent_id)
                emotion = agent_db.get("current_emotion", "평온") if agent_db else None
                ch_name_g = getattr(message.channel, "name", "") or channel_name
                for resp in followup_msgs:
                    for part in _split_for_chat(resp):
                        await send_as_agent(message.channel, agent_id, part)
                        sent_msgs.append(part)
                        db.log_message(ch_name_g, agent_id, part, emotion=emotion)

            # 전송 완료 → speaking 해제 + 메모리 요약 + supervisor 알림
            log_writer.mark_speaking_done(agent_id)
            try:
                from src.core.memory import check_and_summarize
                check_and_summarize(agent_id, channel_name)
            except Exception:
                pass
            from src.bot.supervisors import notify_idle
            asyncio.create_task(notify_idle(channel_name))

            if message.guild:
                for m in sent_msgs:
                    asyncio.create_task(
                        handle_room_request_detection(
                            message.channel, agent_id, m, message.guild
                        )
                    )

    # 에이전트별 랜덤 딜레이로 동시 실행
    responders = persona_agents[:]
    random.shuffle(responders)
    tasks = []
    for i, agent in enumerate(responders):
        delay = random.uniform(0.5, 2.0) * (i + 1) * 0.5
        tasks.append(asyncio.create_task(_process_agent(agent, delay)))

    await asyncio.gather(*tasks, return_exceptions=True)
