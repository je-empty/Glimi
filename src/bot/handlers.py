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
    CMD_PATTERN, QUERY_PATTERN, ACTION_PATTERN,
    CHANNEL_AGENT_MAP, GROUP_PARTICIPANTS,
    _processed_messages, _get_channel_lock, _get_agent_lock,
)
from src.bot.core import send_as_agent, _split_for_chat, _resolve_group_members
from src.bot.mgr_system import (
    parse_and_execute_actions, _forward_action_to_yuna,
    handle_room_request_detection,
)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.webhook_id:
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

    try:
        if channel_name in CHANNEL_AGENT_MAP:
            agent_id = CHANNEL_AGENT_MAP[channel_name]
            await handle_dm(message, agent_id, channel_name, user_message)
            return

        if channel_name.startswith("group-"):
            await handle_group(message, channel_name, user_message)
            return
    except Exception as e:
        log.error(f"[on_message] 처리 중 오류 ({channel_name}): {e}", exc_info=True)
        log_writer.system(f"❌ on_message 오류 ({channel_name}): {e}")
        from src.bot.tasks import _handle_runtime_error
        await _handle_runtime_error(message.guild, channel_name, e)


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

    # -full 파일 찾기
    if "-full" not in file_name:
        base, ext = file_name.rsplit(".", 1) if "." in file_name else (file_name, "png")
        file_name = f"{base}-full.{ext}"

    paths_to_check = [
        os.path.join(str(community.get_avatars_dir()), file_name),
        os.path.join(str(community.ASSETS_DIR / "avatars"), file_name),
    ]

    image_path = None
    for p in paths_to_check:
        if os.path.exists(p):
            image_path = p
            break

    if image_path:
        await send_image_as_agent(channel, agent_id, image_path, caption)
        log_writer.system(f"[이미지] {agent_id} → #{getattr(channel, 'name', '?')}: {file_name}")
    else:
        log_writer.system(f"[이미지] 파일 못 찾음: {file_name}")


def _filter_meta_speech(text: str, agent_id: str) -> str:
    """메타 발언 필터 — ACTION/CMD 실행을 설명하는 발언 제거.
    예: "서유나한테 DM 보냈어", "유나한테 메시지 전달했어" 등"""
    import re
    # "~한테 DM/메시지 보냈/전달" 패턴
    text = re.sub(r'.{1,10}한테\s*(DM|메시지|dm)\s*(보냈|전달|전송).{0,10}', '', text).strip()
    # "~에게 DM 보냈어"
    text = re.sub(r'.{1,10}에게\s*(DM|메시지|dm)\s*(보냈|전달|전송).{0,10}', '', text).strip()
    return text


async def _process_and_send(channel, agent_id, msg, is_mgr, guild, sent_msgs):
    """메시지 하나를 처리해서 전송 + DB 로깅. mgr/creator면 CMD/QUERY, 페르소나면 ACTION 파싱."""
    from src.bot.core import send_system_log
    ch_name = getattr(channel, 'name', '')
    is_creator = (load_profile(agent_id) or {}).get("type") == "creator"
    has_cmd_access = is_mgr or is_creator
    has_cmd = CMD_PATTERN.search(msg) or QUERY_PATTERN.search(msg)
    has_action = ACTION_PATTERN.search(msg)

    # 에이전트 감정 (DB 로깅용)
    agent_db = db.get_agent(agent_id)
    emotion = agent_db.get("current_emotion", "평온") if agent_db else None

    if has_cmd_access and guild and has_cmd:
        # CMD/QUERY — 대화에 안 보이고 시스템 로그로
        agent_name = (load_profile(agent_id) or {}).get("name", agent_id)
        await send_system_log(f"{agent_id} ({agent_name}) {msg}", force=True)
        cleaned = await parse_and_execute_actions(channel, [msg], guild)
        for resp in cleaned:
            for part in _split_for_chat(resp):
                await send_as_agent(channel, agent_id, part)
                sent_msgs.append(part)
                db.log_message(ch_name, agent_id, part, emotion=emotion)
    elif has_action:
        agent_name = (load_profile(agent_id) or {}).get("name", agent_id)
        await send_system_log(f"{agent_id} ({agent_name}) {msg}", force=True)
        actions = ACTION_PATTERN.findall(msg)
        clean_text = ACTION_PATTERN.sub('', msg).strip()
        clean_text = _filter_meta_speech(clean_text, agent_id)
        if clean_text:
            for part in _split_for_chat(clean_text):
                await send_as_agent(channel, agent_id, part)
                sent_msgs.append(part)
                db.log_message(ch_name, agent_id, part, emotion=emotion)
        for action in actions:
            # 이미지 ACTION 처리
            action_str = action.strip()
            if _is_image_action(action_str):
                await _handle_image_action(channel, agent_id, action_str)
            else:
                await _forward_action_to_yuna(agent_id, action_str, guild)
    else:
        for part in _split_for_chat(msg):
            await send_as_agent(channel, agent_id, part)
            sent_msgs.append(part)
            db.log_message(ch_name, agent_id, part, emotion=emotion)


async def handle_dm(message: discord.Message, agent_id: str, channel_name: str, user_message: str):
    """1:1 채널 메시지 처리 — 스트리밍: 메시지 생성 즉시 디스코드 전송"""
    profile = load_profile(agent_id)
    if not profile:
        return

    lock = _get_channel_lock(channel_name)
    is_mgr = profile.get("type") == "mgr"

    async with lock:
        loop = asyncio.get_event_loop()
        msg_queue = asyncio.Queue()

        # 전 에이전트 공통: 스트리밍 생성 + 즉시 전송
        sent_msgs = []
        _tag_buffer = ""  # CMD/QUERY 태그가 여러 줄에 걸칠 때 버퍼

        def _on_message(msg):
            loop.call_soon_threadsafe(msg_queue.put_nowait, msg)

        def _generate():
            runtime.generate_response_streaming(
                agent_id, channel_name, user_message,
                on_message=_on_message,
            )
            loop.call_soon_threadsafe(msg_queue.put_nowait, None)

        def _has_complete_tag(text):
            """CMD/QUERY/ACTION 태그가 완전히 닫혀있는지 확인"""
            return bool(CMD_PATTERN.search(text) or QUERY_PATTERN.search(text) or ACTION_PATTERN.search(text))

        def _has_open_tag(text):
            """[CMD: / [QUERY: / [ACTION: 가 열렸지만 완전히 안 닫힌 상태인지"""
            if "[CMD:" not in text and "[QUERY:" not in text and "[ACTION:" not in text:
                return False
            return not _has_complete_tag(text)

        async def _handle_msg(msg):
            """메시지 처리 — CMD/QUERY 태그가 여러 줄에 걸치면 합침"""
            nonlocal _tag_buffer

            if _tag_buffer:
                _tag_buffer += " " + msg
                if _has_complete_tag(_tag_buffer) or not _has_open_tag(_tag_buffer):
                    full_msg = _tag_buffer
                    _tag_buffer = ""
                    await _process_and_send(
                        message.channel, agent_id, full_msg,
                        is_mgr, message.guild, sent_msgs
                    )
                return

            if _has_open_tag(msg):
                _tag_buffer = msg
                return

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
            await asyncio.sleep(0.1)  # rate limit 방지

        # 버퍼에 남은 불완전 태그 처리 (닫히지 않은 채 끝남)
        if _tag_buffer:
            await _process_and_send(
                message.channel, agent_id, _tag_buffer,
                is_mgr, message.guild, sent_msgs
            )

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
            _tag_buffer = ""

            def _has_complete_tag_g(text):
                return bool(CMD_PATTERN.search(text) or QUERY_PATTERN.search(text) or ACTION_PATTERN.search(text))

            def _has_open_tag_g(text):
                if "[CMD:" not in text and "[QUERY:" not in text and "[ACTION:" not in text:
                    return False
                return not _has_complete_tag_g(text)

            async def _handle_group_msg(msg_text):
                nonlocal _tag_buffer
                if _tag_buffer:
                    _tag_buffer += " " + msg_text
                    if _has_complete_tag_g(_tag_buffer) or not _has_open_tag_g(_tag_buffer):
                        full_msg = _tag_buffer
                        _tag_buffer = ""
                        await _process_and_send(
                            message.channel, agent_id, full_msg,
                            False, message.guild, sent_msgs
                        )
                    return
                if _has_open_tag_g(msg_text):
                    _tag_buffer = msg_text
                    return
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

            # 버퍼에 남은 불완전 태그 처리
            if _tag_buffer:
                await _process_and_send(
                    message.channel, agent_id, _tag_buffer,
                    False, message.guild, sent_msgs
                )

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
