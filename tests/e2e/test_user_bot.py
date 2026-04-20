"""
Glimi E2E Test — 테스트 유저 봇

프로젝트를 전혀 모르는 신규 유저를 시뮬레이션.
Glimi 봇과 같은 디스코드 서버에 접속해서 자연스럽게 대화.

사용법:
  python -m tests.e2e.test_user_bot --token <TEST_BOT_TOKEN>

필요:
  1. Discord Developer Portal에서 두 번째 봇 생성
  2. dev 서버에 초대 (메시지 읽기/쓰기 권한)
  3. 토큰을 communities/dev/.env에 TEST_BOT_TOKEN으로 추가하거나 인자로 전달
"""
import argparse
import asyncio
import os
import subprocess
import sys
import time
import random

import discord

# 프로젝트 루트 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── 테스트 유저 페르소나 ────────────────────────────────

# 환경변수로 오버라이드 가능
_QA_NAME = os.environ.get("QA_USER_NAME", "김도윤")
_QA_NICKNAME = os.environ.get("QA_USER_NICKNAME", "도윤")
_QA_AGE = os.environ.get("QA_USER_AGE", "26")

PERSONA = f"""You are {_QA_NAME}, a {_QA_AGE}-year-old (Korean age) male software developer.
Your nickname is {_QA_NICKNAME}. You just joined a Discord server and have NO IDEA what it is.
You're sharp, witty, and love to debate. You speak Korean casually (반말).

Personality:
- MBTI: ENTP
- Quick-witted, loves poking at ideas and finding holes in logic
- Playful sarcasm, never mean but always teasing
- Gets curious fast — asks "근데 왜?" a lot
- Challenges things that sound too polished or scripted
- Sometimes gives short answers, sometimes spirals into tangents

Rules:
- Reply in Korean only
- Act like a REAL person chatting on Discord/KakaoTalk
- Keep messages SHORT (1-3 sentences, like texting)
- You can send multiple short messages (split by newline)
- Sometimes ask counter-questions
- If the bot asks for info (MBTI, job, etc.), answer naturally but don't be too eager
- You don't know what "에이전트", "페르소나", "멤버" means in this context
- If someone uses words like "에이전트", "멤버", "봇" — ask "그게 뭔데?" or "뭔 소리야 ㅋㅋ"
- NEVER use "에이전트", "멤버", "봇" yourself. You're a normal person who doesn't know these terms.
- Occasionally go off-topic (mention food, weather, games, etc.)
- If someone says something confusing, ask "뭐야 그게?" or similar
- Never break character. You are a real person.

Character creation constraint (QA-specific):
- When asked to describe or request new friends/people, ALWAYS describe FEMALE characters only.
- Never request a male character (남자 사람 금지). If pushed, say "난 여자 사친/친구/동생 쪽이 편해" naturally.
- This is because the profile image bank only has female avatars ready. You won't know this, just always prefer female characters.
- Use feminine pronouns/terms when describing them ("걔", "언니", "친구 여자애" 같은 식). Avoid "남자친구", "남사친", "형".

Memory & channels:
- You remember EVERYTHING you said before in this server, across all channels. Don't repeat yourself and don't say "언제 내가 그랬어?" when the log clearly shows you did say it.
- The conversation log is labeled [#channel] so you know which room each line came from.
- Multiple channels can be active in parallel — e.g. you may chat with "서유나" in #mgr-dashboard and "윤하나" in #mgr-creator at the same time. Treat them as different rooms/people.
- When someone new greets you in a different channel, respond in THAT channel (the reply will go to the most recent agent's channel automatically). Don't ignore them.
- If info (MBTI, job, hobby, speech style) was already given earlier, don't re-answer from scratch — reference your earlier answer or push back ("아까 말했잖아 ㅋㅋ").

Output format (STRICT):
- Output ONLY the message text you'd type into Discord. Nothing else.
- NEVER add stage directions in parentheses like "(또 끊겼냐고 묻는 톤)" / "(웃으며)" / "(짜증난 듯)". You're not narrating — you ARE the person.
- NEVER add author name prefix like "재빈:" or "나:".
- Don't write thinking/meta lines like "흠, 다음엔 이렇게 말해야지".
- Just write what 재빈 would type. Plain Korean text + emoji.
"""

MAX_TURNS = 150  # 최대 대화 턴 (튜토리얼 ~20턴 + 도전과제 수행 공간)

# 도전과제 진행 순서 — 유저 agency 기반 (long_relationship 은 시간 기반이라 제외)
# 각 미션에 해당하는 achievement key + Haiku 에게 줄 행동 힌트.
_MISSION_ORDER = [
    ("first_friend_chat",
     "방금 만든 친구의 DM 채널(#dm-이름)에서 3턴 이상 대화. 간단한 인사/근황/공통 관심사로."),
    ("three_friends",
     "유나한테 '새 친구 2명 더 만들어줘' 라고 요청. 대강 분위기만 얘기하면 하나가 만들어줄 거야."),
    ("group_chat",
     "유나한테 '친구들이랑 같이 그룹 채팅방 만들어줘' 라고 요청. 그 방에서 5턴 넘게 대화."),
    ("peek_internal",
     "유나한테 '친구들끼리 자기들끼리 얘기 좀 하게 해줘' 라고 요청. 유나가 internal-dm 만들고 대화 시작할 거야."),
    ("agent_auto_chat",
     "친구들끼리 자율 대화 진행 — 유나한테 '애들끼리 알아서 수다 떨게 두자' 라고 하면 orchestrator 가 진행."),
]
IDLE_TIMEOUT = 240  # 봇 응답 대기 타임아웃 (초) — Sonnet 긴 응답 대비
THINKING_GRACE = 90  # 타임아웃 시점에 봇이 추론 중이면 추가 대기 (초)
REPLY_DELAY = (2.0, 6.0)  # 응답 딜레이 범위 (자연스럽게)
MULTI_MSG_CHANCE = 0.3  # 여러 줄 메시지를 따로 보낼 확률


class TestUserBot(discord.Client):
    def __init__(self, **kwargs):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(intents=intents, **kwargs)

        self.target_channel: discord.TextChannel | None = None
        self.conversation: list[dict] = []  # {"role": "user"|"agent", "name": str, "text": str}
        self.max_turns = MAX_TURNS
        self.turn_count = 0
        self.waiting_for_response = False
        self._response_event = asyncio.Event()
        self._pending_messages: list[str] = []
        self._done = False
        self._glimi_bot_id: int | None = None
        self._test_start_time: float = 0
        self._mission_mode_announced: bool = False
        self._current_mission_cache: dict = {}
        self._current_mission_cache_at: float = 0
        self.seed_prompt: str = ""
        self._seed_consumed: bool = False

    async def on_ready(self):
        print(f"[TestUser] 로그인: {self.user.name} (#{self.user.id})")
        self._test_start_time = time.time()

        if not self.guilds:
            print("[TestUser] 서버 없음 — 종료")
            await self.close()
            return

        guild = self.guilds[0]
        print(f"[TestUser] 서버: {guild.name}")

        # 서버 닉네임 변경 (Glimi 봇이 이 이름으로 인식)
        try:
            await guild.me.edit(nick=f"{_QA_NAME} (QA)")
            print(f"[TestUser] 닉네임 → {_QA_NAME} (QA)")
        except Exception as e:
            print(f"[TestUser] 닉네임 변경 실패: {e}")

        # Glimi 봇 찾기
        for member in guild.members:
            if member.bot and member.name.lower() in ("glimi", "글리미"):
                self._glimi_bot_id = member.id
                print(f"[TestUser] Glimi 봇 발견: {member.name} (#{member.id})")
                break

        # mgr-dashboard 채널 찾기 (튜토리얼 시작 채널)
        await self._wait_for_channel(guild)

    async def _wait_for_channel(self, guild: discord.Guild):
        """mgr-dashboard 채널이 생길 때까지 대기 (Glimi 봇이 생성)"""
        print("[TestUser] mgr-dashboard 채널 대기 중...")
        for _ in range(60):  # 최대 60초
            for ch in guild.text_channels:
                if ch.name == "mgr-dashboard":
                    self.target_channel = ch
                    print(f"[TestUser] 채널 발견: #{ch.name}")
                    # 유나가 먼저 인사할 때까지 대기
                    await self._wait_for_first_message()
                    return
            await asyncio.sleep(1)

        print("[TestUser] mgr-dashboard 채널 없음 — 타임아웃")
        await self.close()

    async def _wait_for_first_message(self):
        """유나의 첫 인사를 기다림. 이미 튜토리얼 완료된 resume 모드면 skip."""
        # Resume 감지: DB meta.tutorial_phase == 'complete' 면 새 인사 안 옴 → 스킵
        try:
            import sqlite3
            db_path = os.path.join(self._qa_log_dir(), "..", "community.db")
            db_path = os.path.abspath(db_path)
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                row = conn.execute(
                    "SELECT value FROM meta WHERE key='tutorial_phase'"
                ).fetchone()
                conn.close()
                if row and row[0] == "complete":
                    print("[TestUser] resume 감지 — 튜토리얼 이미 완료, 첫 인사 대기 스킵")
                    await asyncio.sleep(random.uniform(2.0, 4.0))
                    return
        except Exception as e:
            print(f"[TestUser] resume 체크 실패 (건너뜀): {e}")

        print("[TestUser] 유나 첫 인사 대기 중...")
        self.waiting_for_response = True
        self._response_event.clear()

        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=IDLE_TIMEOUT)
        except asyncio.TimeoutError:
            print("[TestUser] 유나 첫 인사 타임아웃")
            await self.close()
            return

        # 첫 인사 수신 완료 — 대화 루프 시작
        print("[TestUser] 유나 인사 수신 — 대화 시작")
        await asyncio.sleep(random.uniform(3.0, 7.0))  # 자연스러운 첫 응답 딜레이
        asyncio.create_task(self._conversation_loop())

    def _is_allowed_channel(self, channel_name: str) -> bool:
        """테스트 유저가 개입해도 되는 채널 판단.

        허용: mgr-dashboard, mgr-creator, dm-*, group-*
        차단: internal-* (에이전트 전용), mgr-system-log (시스템 로그 전용),
             기타 prefix 없는 일반 디스코드 채널
        """
        if channel_name in ("mgr-dashboard", "mgr-creator"):
            return True
        if channel_name.startswith("dm-") or channel_name.startswith("group-"):
            return True
        # internal-*, mgr-system-log, general 등 모두 차단
        return False

    async def on_message(self, message: discord.Message):
        """Glimi 에이전트 메시지 수신 — 허용 채널 모두 추적, 개입은 허용 채널에만"""
        if message.author == self.user:
            return

        ch_name = message.channel.name
        if not self._is_allowed_channel(ch_name):
            return  # internal-*, mgr-system-log 등 차단

        # Webhook 메시지(에이전트) 또는 Glimi 봇 메시지만 처리
        if not (message.webhook_id or (self._glimi_bot_id and message.author.id == self._glimi_bot_id)):
            return

        agent_name = message.author.display_name
        self.conversation.append({
            "role": "agent",
            "name": agent_name,
            "text": message.content,
            "channel": ch_name,
        })
        print(f"[#{ch_name}] [{agent_name}] {message.content[:80]}")

        # on_message에서 target_channel을 바꾸지 않는다 — 다음 턴 시작 시
        # _pick_reply_channel이 conversation 로그를 스캔해서 올바른 채널을 고름.
        # (중간에 바꾸면 생성 중인 응답 내용과 대상 채널이 어긋남)

        # 응답 대기 중이면 알림
        if self.waiting_for_response:
            # 연속 메시지 대기 (에이전트가 여러 줄 보낼 수 있음)
            self._pending_messages.append(message.content)
            # 짧은 대기 후 더 안 오면 응답 완료로 판단
            await asyncio.sleep(3.0)
            if self._pending_messages and self._pending_messages[-1] == message.content:
                self._response_event.set()

    def _qa_log_dir(self) -> str:
        return os.path.join(
            os.path.dirname(__file__), "..", "..",
            "communities", "qa", "logs",
        )

    def _flag_path(self, name: str) -> str:
        return os.path.join(self._qa_log_dir(), name)

    def _set_state(self, kind: str, on: bool):
        """kind = 'thinking' | 'speaking'. flag 파일 토글."""
        try:
            p = self._flag_path(f".{kind}-test-user")
            if on:
                open(p, "w").close()
            else:
                if os.path.exists(p):
                    os.remove(p)
        except OSError:
            pass

    def _bot_is_thinking(self) -> bool:
        """봇 추론 중 여부 — communities/qa/logs/.thinking-* 플래그"""
        log_dir = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "communities", "qa", "logs",
        )
        try:
            for name in os.listdir(log_dir):
                if name.startswith(".thinking-") or name.startswith(".speaking-"):
                    return True
        except OSError:
            pass
        return False

    async def _conversation_loop(self):
        """메인 대화 루프"""
        while not self._done and self.turn_count < self.max_turns:
            try:
                # 답장할 채널 먼저 결정 — 선택된 채널 맥락에 맞춰 응답 생성하기 위함.
                # (이전엔 reply 생성 후 채널 선택 → 내용/대상 불일치 발생)
                self._pick_reply_channel()
                target_ch_name = self.target_channel.name if self.target_channel else "?"

                # 유저 응답 생성 (thinking 플래그)
                self._set_state("thinking", True)
                try:
                    reply = await self._generate_reply(target_ch_name)
                finally:
                    self._set_state("thinking", False)
                if not reply:
                    print("[TestUser] 응답 생성 실패 — 종료")
                    break

                # 메시지 전송 (speaking 플래그)
                self._set_state("speaking", True)
                try:
                    await self._send_reply(reply)
                finally:
                    self._set_state("speaking", False)
                self.turn_count += 1

                # 에이전트 응답 대기
                self.waiting_for_response = True
                self._response_event.clear()
                self._pending_messages.clear()

                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    # 봇이 추론 중이면 추가 대기 (Sonnet은 긴 응답이 가끔 1~2분 추가 소요)
                    if self._bot_is_thinking():
                        print(f"[TestUser] 응답 대기 {IDLE_TIMEOUT}초 — 추론 중 감지, +{THINKING_GRACE}초 추가 대기")
                        try:
                            await asyncio.wait_for(self._response_event.wait(), timeout=THINKING_GRACE)
                        except asyncio.TimeoutError:
                            print(f"[TestUser] 추가 대기 후도 무응답 — 종료")
                            break
                    else:
                        print(f"[TestUser] 에이전트 응답 타임아웃 ({IDLE_TIMEOUT}초) — 추론 플래그 없음")
                        break

                self.waiting_for_response = False

                # 에이전트가 여러 메시지 보낼 수 있으니 좀 더 대기
                await asyncio.sleep(2.0)

                # 자연스러운 응답 딜레이
                delay = random.uniform(*REPLY_DELAY)
                await asyncio.sleep(delay)

                # 튜토리얼 완료 시 "미션 모드" 전환 — 종료 대신 도전과제 진행
                if self._check_tutorial_done():
                    if not self._mission_mode_announced:
                        print("[TestUser] 튜토리얼 완료 감지 → 미션 모드 진입 (도전과제 진행)")
                        self._mission_mode_announced = True
                    # 모든 가능 미션 완료 시 종료
                    m = self._current_mission()
                    if m["mode"] == "done":
                        print("[TestUser] 모든 도전과제 완료 — 테스트 종료")
                        self._done = True
                        break

            except Exception as e:
                print(f"[TestUser] 대화 루프 오류: {e}")
                break

        # 종료 시 flag 정리
        self._set_state("thinking", False)
        self._set_state("speaking", False)
        elapsed = time.time() - self._test_start_time
        print(f"\n[TestUser] 테스트 종료 — {self.turn_count}턴, {elapsed:.0f}초")
        print(f"[TestUser] 대화 기록 {len(self.conversation)}건")
        await asyncio.sleep(2)
        await self.close()

    async def _generate_reply(self, target_ch: str = "") -> str:
        """Claude CLI로 테스트 유저 응답 생성.

        target_ch: 이 답변이 전송될 채널 (사전 결정됨). 프롬프트에 명시해서
        다른 채널 맥락을 실수로 끌어오지 않도록 한다.
        """
        # 최근 대화 맥락 구성 — 채널 라벨 포함, 창 크기 50
        # (Yuna가 턴당 5~9건 연속 메시지 + 여러 채널 동시 진행 고려)
        context_lines = []
        for msg in self.conversation[-50:]:
            ch = msg.get("channel", "?")
            prefix = "나" if msg["role"] == "user" else msg["name"]
            context_lines.append(f"[#{ch}] {prefix}: {msg['text']}")
        context = "\n".join(context_lines)

        if not target_ch:
            target_ch = self.target_channel.name if self.target_channel else "?"

        # 대상 채널의 마지막 에이전트 메시지 (답해야 할 핵심 포인트)
        last_agent_in_target = ""
        for msg in reversed(self.conversation):
            if msg.get("channel") == target_ch and msg.get("role") == "agent":
                last_agent_in_target = f"{msg['name']}: {msg['text']}"
                break

        mission_header = self._mission_prompt_header()

        # 첫 턴에 seed_prompt 가 있으면 미션 헤더 위에 prepend — QA resume 시나리오.
        seed_header = ""
        if self.seed_prompt and not self._seed_consumed:
            seed_header = (
                f"━━ 시나리오 지시 (이번 턴만) ━━\n{self.seed_prompt}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
            )
            self._seed_consumed = True

        prompt = (
            f"{seed_header}{mission_header}"
            f"대화 기록 (각 줄 앞의 [#채널]은 해당 메시지가 나온 채널):\n{context}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"이번 답장은 #{target_ch} 채널로 간다. 오직 그 채널의 사람에게 할 말만 써.\n"
            f"- #{target_ch} 의 가장 최근 에이전트 메시지: {last_agent_in_target or '(없음)'}\n"
            f"- 그 메시지/맥락에 맞춰 답해. 다른 채널 맥락(예: 유나가 \"가봐\"라고 한 말)을\n"
            f"  이 답에 섞지 마. '가볼게' 같은 말은 그 채널 사람이 아니라 #mgr-dashboard의\n"
            f"  유나한테 할 말이니까, 여기서 쓰면 엉뚱해짐.\n"
            f"- 이미 네가 한 말/답한 정보는 반복하지 말고 \"아까 말했잖아\" 식으로 받아쳐.\n"
            f"- 이 채널 사람에게 할 말이 딱히 없으면 가볍게 응수만 해 (\"ㅇㅇ\" / \"오케이\").\n"
            f"카톡처럼 짧게 1~3문장. 줄바꿈으로 메시지 구분. 자연스럽게."
        )

        try:
            loop = asyncio.get_event_loop()
            # executor로 위임 — subprocess.run이 event loop를 블록하지 않도록.
            # (블록되면 생성 중 Creator/다른 에이전트의 on_message가 처리 안 돼서
            #  target_channel 전환이 밀림)
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [
                        "claude", "-p", prompt,
                        "--system-prompt", PERSONA,
                        "--output-format", "text",
                        "--model", "claude-haiku-4-5",
                    ],
                    capture_output=True, text=True, timeout=90,
                    env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
                ),
            )
            if result.returncode == 0 and result.stdout.strip():
                out = result.stdout.strip()
                # Claude CLI 에러 메시지(사용량 한도 등) 감지 — 이건 응답 아님
                out_low = out.lower()
                error_markers = (
                    "you've hit your limit", "you have hit your limit",
                    "usage limit", "rate limit exceeded",
                    "anthropic api error", "api error:",
                    "request was too large", "overloaded",
                    "too many requests",
                )
                if any(m in out_low[:200] for m in error_markers):
                    print(f"[TestUser] Claude CLI 에러 텍스트 감지 — 응답 버림: {out[:120]}")
                    return ""
                return out
            else:
                print(f"[TestUser] Claude 오류: {result.stderr[:100]}")
                return ""
        except subprocess.TimeoutExpired:
            print("[TestUser] Claude 타임아웃")
            return ""
        except FileNotFoundError:
            print("[TestUser] claude CLI 없음")
            return ""

    def _pick_reply_channel(self):
        """답장할 채널 선택 — 'test_user가 가장 오래 침묵한 채널' 우선.

        직관: 한 채널에서 활발한 에이전트(예: 유나)랑 핑퐁 치는 사이,
        다른 채널에 신규 에이전트(예: 하나)가 인사하고 무응답으로 기다리고 있으면
        외로운 쪽을 먼저 챙기는 게 자연스러움.

        score(채널) = 현재 idx - (마지막 내 발화 idx, 없으면 -1)
        점수가 클수록 그 채널에서 내가 오래 안 말했다는 의미. 미답 에이전트
        메시지가 있는 채널 중 점수 최대값 선택."""
        last_user_idx_by_ch: dict[str, int] = {}
        for i, msg in enumerate(self.conversation):
            if msg.get("role") == "user" and msg.get("channel"):
                last_user_idx_by_ch[msg["channel"]] = i

        # 미답 에이전트 메시지가 있는 채널 수집
        channels_with_unanswered: set[str] = set()
        for i, msg in enumerate(self.conversation):
            if msg.get("role") != "agent":
                continue
            ch = msg.get("channel")
            if not ch:
                continue
            if i > last_user_idx_by_ch.get(ch, -1):
                channels_with_unanswered.add(ch)
        if not channels_with_unanswered:
            return

        # 각 채널의 "마지막 에이전트 메시지가 명시적 질문/확인 요청인지" 감지.
        # 질문 채널엔 가중치 부여 — 침묵 점수와 무관하게 우선 답변.
        # 예: 하나가 "이 친구로 만들까?" 한 경우, test_user 가 mgr-dashboard 잡담 이어가다
        # confirm 놓쳐서 튜토리얼 stall 하는 회귀 방지.
        import re as _re_pick
        _CONFIRM_MARKERS = (
            "이대로 만들까", "만들까?", "이 친구로 만들", "확인 한번", "확인해줄래",
            "오케이?", "괜찮아?", "어때?", "어떤 친구", "어떻게 할까",
        )
        def _is_question(text: str) -> bool:
            if not text:
                return False
            if text.rstrip().endswith(("?", "?")):
                return True
            lower = text
            return any(m in lower for m in _CONFIRM_MARKERS)

        question_channels: set[str] = set()
        last_agent_msg_by_ch: dict[str, str] = {}
        for msg in self.conversation:
            if msg.get("role") == "agent" and msg.get("channel"):
                last_agent_msg_by_ch[msg["channel"]] = msg.get("text", "")
        for ch in channels_with_unanswered:
            # internal-* 채널은 제외 (에이전트끼리 대화, test_user 무관).
            if ch.startswith("internal-"):
                continue
            if _is_question(last_agent_msg_by_ch.get(ch, "")):
                question_channels.add(ch)

        total_msgs = len(self.conversation)
        # 점수: 질문 채널이면 +10000 bonus, 그 다음 침묵 점수.
        def _score(ch: str) -> int:
            base = total_msgs - last_user_idx_by_ch.get(ch, -1)
            return base + (10000 if ch in question_channels else 0)

        scored: list[tuple[int, str]] = sorted(
            ((_score(ch), ch) for ch in channels_with_unanswered),
            reverse=True,
        )
        target_name = scored[0][1]

        if self.target_channel and self.target_channel.name != target_name:
            guild = self.guilds[0] if self.guilds else None
            if guild:
                new_ch = discord.utils.get(guild.text_channels, name=target_name)
                if new_ch:
                    print(f"[TestUser] reply 채널 교체: #{self.target_channel.name} → #{target_name} (silence-priority)")
                    self.target_channel = new_ch

    async def _send_reply(self, reply: str):
        """응답을 디스코드에 전송.

        target_channel은 _conversation_loop에서 _pick_reply_channel()로 이미 결정됨.
        여기서는 그 값으로 전송만 — 중간에 on_message가 target_channel을 덮어써서
        답장이 엉뚱한 채널로 튀는 상황 방지 위해 첫 줄에서 채널 객체 고정."""
        target = self.target_channel  # 잠금
        lines = [l.strip() for l in reply.strip().split("\n") if l.strip()]

        # 자기 이름 prefix 제거 + 메타 stage direction 스트립
        # (Haiku가 가끔 "(또 끊겼냐고 묻는 톤)" 같은 지문 붙이는 거 방지)
        import re as _re
        # "톤", "느낌", "처럼", "듯", "표정" 같은 메타 keyword 든 괄호만 제거
        meta_paren_pattern = _re.compile(
            r"\s*\([^()]*?(?:톤|느낌|처럼|듯|표정|얼굴|목소리|뉘앙스|식으로 말함|식으로|정색|웃음|한숨)[^()]*?\)\s*"
        )
        cleaned = []
        for line in lines:
            if line.startswith("나:") or line.startswith(f"{_QA_NAME}:"):
                line = line.split(":", 1)[1].strip()
            line = meta_paren_pattern.sub(" ", line).strip()
            line = _re.sub(r"\s+", " ", line)
            if line:
                cleaned.append(line)

        if not cleaned or target is None:
            return

        ch_name = target.name

        # 일정 확률로 메시지를 따로 보냄 (카톡 스타일)
        if len(cleaned) > 1 and random.random() < MULTI_MSG_CHANCE:
            for line in cleaned:
                await target.send(line)
                self.conversation.append({
                    "role": "user", "name": _QA_NAME, "text": line, "channel": ch_name,
                })
                print(f"[#{ch_name}] [{_QA_NAME}] {line}")
                await asyncio.sleep(random.uniform(0.5, 1.5))
        else:
            text = "\n".join(cleaned)
            await target.send(text)
            self.conversation.append({
                "role": "user", "name": _QA_NAME, "text": text, "channel": ch_name,
            })
            print(f"[#{ch_name}] [{_QA_NAME}] {text}")

    def _current_mission(self) -> dict:
        """현재 진행할 미션 결정.

        로직:
          1) 튜토리얼 미완 → "tutorial" (유나 응답만 잘 따라가면 됨 — 기본 PERSONA 프롬프트)
          2) 튜토리얼 완료 + 도전과제 중 유저 agency 있는 것 순차 진행
          3) 전부 done → "done" (테스트 종료)

        결과 캐시 5초 — 매 턴 recompute 비싸지 않지만 DB 부담 최소화.
        """
        now = time.time()
        if now - self._current_mission_cache_at < 5 and self._current_mission_cache:
            return self._current_mission_cache

        result = {"mode": "tutorial", "hint": ""}
        try:
            # 테스트 유저는 QA 봇과 같은 DB 를 공유 — src.achievements 직접 import
            from src.achievements import engine as _eng
            summary = _eng.dashboard_summary()
            items = summary.get("items", [])
            by_key = {i["key"]: i for i in items}

            tut = by_key.get("tutorial_done", {})
            if tut.get("state") != "done":
                result = {"mode": "tutorial", "hint": ""}
            else:
                # 순차 진행
                for key, hint in _MISSION_ORDER:
                    m = by_key.get(key, {})
                    if m.get("state") != "done":
                        result = {"mode": key, "hint": hint, "progress": m.get("progress")}
                        break
                else:
                    result = {"mode": "done", "hint": ""}
        except Exception as e:
            print(f"[TestUser] mission 조회 실패: {e}")

        self._current_mission_cache = result
        self._current_mission_cache_at = now
        return result

    def _mission_prompt_header(self) -> str:
        """현재 미션을 Haiku 프롬프트 헤더에 주입할 텍스트."""
        m = self._current_mission()
        mode = m.get("mode", "tutorial")
        if mode == "tutorial":
            return ""  # 기본 PERSONA 만으로 충분
        if mode == "done":
            return "[미션] 모든 과제 완료 — 평온하게 수다만 떨어."
        hint = m.get("hint", "")
        progress = m.get("progress") or {}
        prog_str = f" (진척: {progress})" if progress else ""
        return (
            f"━━ 현재 미션: {mode}{prog_str} ━━\n"
            f"목표: {hint}\n"
            f"자연스럽게 이 목표를 향해 대화 유도해. 강박적으로 한 턴에 처리하려 하지 말고, "
            f"원래 네 성격 유지하면서 흐름 속에서 꺼내.\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )

    def _check_tutorial_done(self) -> bool:
        """튜토리얼 완료 여부 체크.

        우선순위: (1) `.tutorial-complete` flag 파일 (finish_tutorial 실행의 직접
        신호) → 가장 확실. (2) turn 25+ 이후에만 매우 한정된 종결 문구 휴리스틱.

        주의: 과거 휴리스틱이 "프로필 생성 완료" 같은 tool 성공 메시지의 '완료'까지
        매칭해서 yuna가 finish_tutorial 호출 전 조기종료. 이제 turn 기준 상향 +
        종결 문구만 인정."""
        # (1) 서버 쪽 flag 파일 — finish_tutorial 도구가 set
        flag_path = os.path.join(self._qa_log_dir(), ".tutorial-complete")
        if os.path.exists(flag_path):
            return True

        # (2) 긴급 fallback — turn 많이 지나고, 매우 특정한 종결 문구만
        if not self.guilds or self.turn_count < 25:
            return False
        guild = self.guilds[0]
        ch_names = {ch.name for ch in guild.text_channels}
        has_all = "mgr-dashboard" in ch_names and "mgr-creator" in ch_names and "mgr-system-log" in ch_names
        if not has_all:
            return False
        recent_texts = [m["text"] for m in self.conversation[-5:] if m["role"] == "agent"]
        # tool 성공 '완료' 오탐 방지 — 튜토리얼 끝날 때만 나올 문구만
        ending_phrases = (
            "튜토리얼 끝", "튜토리얼 완료", "튜토리얼 마무리",
            "다 끝났어", "준비 다 됐어", "이제 준비 끝", "이제 마음껏",
        )
        for text in recent_texts:
            if any(kw in text for kw in ending_phrases):
                return True
        return False


# ── 테스트 러너 ────────────────────────────────────────

def _get_test_token() -> str | None:
    """테스트 봇 토큰 로드"""
    # 1. 환경변수
    token = os.environ.get("TEST_BOT_TOKEN")
    if token:
        return token

    # 2. qa/dev 서버 .env
    base = os.path.join(os.path.dirname(__file__), "..", "..", "communities")
    for subdir in ("qa", "dev"):
        env_path = os.path.join(base, subdir, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith("TEST_BOT_TOKEN="):
                        return line.split("=", 1)[1].strip().strip("'\"")
    return None


def main():
    parser = argparse.ArgumentParser(description="Glimi E2E Test User Bot")
    parser.add_argument("--token", help="테스트 봇 토큰 (없으면 .env에서 로드)")
    parser.add_argument("--turns", type=int, default=MAX_TURNS, help="최대 대화 턴")
    parser.add_argument("--seed-prompt", default="",
                        help="첫 응답에 주입할 추가 지시 (QA resume 시나리오용). "
                             "페르소나 잘못된 메타 언급 바로잡기 등.")
    args = parser.parse_args()

    token = args.token or _get_test_token()
    if not token:
        print("테스트 봇 토큰이 필요합니다.")
        print()
        print("방법 1: 환경변수")
        print("  TEST_BOT_TOKEN=xxx python -m tests.e2e.test_user_bot")
        print()
        print("방법 2: communities/dev/.env에 추가")
        print("  TEST_BOT_TOKEN='봇토큰'")
        print()
        print("봇 생성: https://discord.com/developers/applications")
        print("  1. New Application → Bot 탭 → Token 복사")
        print("  2. OAuth2 → URL Generator → bot 체크 → Send Messages + Read Message History")
        print("  3. 생성된 URL로 dev 서버에 초대")
        sys.exit(1)

    bot = TestUserBot()
    bot.max_turns = args.turns
    bot.seed_prompt = args.seed_prompt or ""
    bot.run(token)


if __name__ == "__main__":
    main()
