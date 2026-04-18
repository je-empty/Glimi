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

MAX_TURNS = 50  # 최대 대화 턴
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

        # mgr-dashboard 채널 찾기 (온보딩 시작 채널)
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
        """유나의 첫 인사를 기다림"""
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

        # 에이전트가 다른 허용 채널에서 말 걸면 활성 채널 전환 (실사용자 모방)
        if self.target_channel and message.channel.id != self.target_channel.id:
            print(f"[TestUser] 활성 채널 전환: #{self.target_channel.name} → #{ch_name}")
            self.target_channel = message.channel

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
                # 유저 응답 생성 (thinking 플래그)
                self._set_state("thinking", True)
                try:
                    reply = await self._generate_reply()
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

                # 온보딩 완료 체크
                if self._check_onboarding_done():
                    print("[TestUser] 온보딩 완료 감지 — 테스트 종료")
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

    async def _generate_reply(self) -> str:
        """Claude CLI로 테스트 유저 응답 생성"""
        # 최근 대화 맥락 구성 — 채널 라벨 포함, 창 크기 50
        # (Yuna가 턴당 5~9건 연속 메시지 + 여러 채널 동시 진행 고려)
        context_lines = []
        for msg in self.conversation[-50:]:
            ch = msg.get("channel", "?")
            prefix = "나" if msg["role"] == "user" else msg["name"]
            context_lines.append(f"[#{ch}] {prefix}: {msg['text']}")
        context = "\n".join(context_lines)

        target_ch = self.target_channel.name if self.target_channel else "?"
        prompt = (
            f"대화 기록 (각 줄 앞의 [#채널]은 해당 메시지가 나온 채널):\n{context}\n\n"
            f"지금 네가 답장할 활성 채널: #{target_ch}\n"
            f"위 로그 전체를 기억하고 다음 답장을 해.\n"
            f"- 이미 네가 한 말/답한 정보는 반복하지 말고 \"아까 말했잖아\" 식으로 받아쳐.\n"
            f"- 다른 채널에서 누가 인사하면 그 사람에게 반응하되 지금 활성 채널에 쓸 답이면 돼.\n"
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
                        "--model", "claude-haiku-4-5-20251001",
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

        total_msgs = len(self.conversation)
        # 점수: 내가 마지막 발화 이후 흐른 idx 거리 (0이면 방금 답함, 클수록 오래 침묵)
        scored: list[tuple[int, str]] = [
            (total_msgs - last_user_idx_by_ch.get(ch, -1), ch)
            for ch in channels_with_unanswered
        ]
        scored.sort(reverse=True)
        target_name = scored[0][1]

        if self.target_channel and self.target_channel.name != target_name:
            guild = self.guilds[0] if self.guilds else None
            if guild:
                new_ch = discord.utils.get(guild.text_channels, name=target_name)
                if new_ch:
                    print(f"[TestUser] reply 채널 교체: #{self.target_channel.name} → #{target_name} (silence-priority)")
                    self.target_channel = new_ch

    async def _send_reply(self, reply: str):
        """응답을 디스코드에 전송"""
        # 대기 중인 on_message 태스크(Creator 메시지 등)에 먼저 기회 줘서
        # target_channel이 최신 상태로 갱신되도록 함
        await asyncio.sleep(0)
        # 미답 에이전트 메시지 있는 채널 중 가장 오래된 쪽으로 target_channel 조정
        self._pick_reply_channel()
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

        if not cleaned:
            return

        ch_name = self.target_channel.name if self.target_channel else "?"

        # 일정 확률로 메시지를 따로 보냄 (카톡 스타일)
        if len(cleaned) > 1 and random.random() < MULTI_MSG_CHANCE:
            for line in cleaned:
                await self.target_channel.send(line)
                self.conversation.append({
                    "role": "user", "name": _QA_NAME, "text": line, "channel": ch_name,
                })
                print(f"[#{ch_name}] [{_QA_NAME}] {line}")
                await asyncio.sleep(random.uniform(0.5, 1.5))
        else:
            text = "\n".join(cleaned)
            await self.target_channel.send(text)
            self.conversation.append({
                "role": "user", "name": _QA_NAME, "text": text, "channel": ch_name,
            })
            print(f"[#{ch_name}] [{_QA_NAME}] {text}")

    def _check_onboarding_done(self) -> bool:
        """온보딩 완료 여부 체크 — 채널 구조 변화로 판단"""
        if not self.guilds:
            return False
        guild = self.guilds[0]
        ch_names = {ch.name for ch in guild.text_channels}
        # mgr-creator 채널이 생기면 온보딩 Phase 2 진행 중
        # 유나가 채널 설명까지 하면 완료
        has_all = "mgr-dashboard" in ch_names and "mgr-creator" in ch_names and "mgr-system-log" in ch_names
        if has_all and self.turn_count > 5:
            # 마지막 메시지에서 온보딩 완료 힌트 체크
            recent_texts = [m["text"] for m in self.conversation[-5:] if m["role"] == "agent"]
            for text in recent_texts:
                if any(kw in text for kw in ("완료", "끝", "다 됐", "준비 됐", "시작해", "둘러봐")):
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
    bot.run(token)


if __name__ == "__main__":
    main()
