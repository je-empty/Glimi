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
"""

MAX_TURNS = 50  # 최대 대화 턴
IDLE_TIMEOUT = 120  # 봇 응답 대기 타임아웃 (초)
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

    async def on_message(self, message: discord.Message):
        """Glimi 에이전트 메시지 수신"""
        if message.author == self.user:
            return
        if not self.target_channel:
            return
        if message.channel.id != self.target_channel.id:
            # 다른 채널 메시지도 기록 (mgr-creator 등)
            return

        # Webhook 메시지 (에이전트) 또는 Glimi 봇 메시지
        if message.webhook_id or (self._glimi_bot_id and message.author.id == self._glimi_bot_id):
            agent_name = message.author.display_name
            self.conversation.append({
                "role": "agent",
                "name": agent_name,
                "text": message.content,
            })
            print(f"[{agent_name}] {message.content[:80]}")

            # 응답 대기 중이면 알림
            if self.waiting_for_response:
                # 연속 메시지 대기 (에이전트가 여러 줄 보낼 수 있음)
                self._pending_messages.append(message.content)
                # 짧은 대기 후 더 안 오면 응답 완료로 판단
                await asyncio.sleep(3.0)
                if self._pending_messages and self._pending_messages[-1] == message.content:
                    self._response_event.set()

    async def _conversation_loop(self):
        """메인 대화 루프"""
        while not self._done and self.turn_count < self.max_turns:
            try:
                # 유저 응답 생성
                reply = await self._generate_reply()
                if not reply:
                    print("[TestUser] 응답 생성 실패 — 종료")
                    break

                # 메시지 전송
                await self._send_reply(reply)
                self.turn_count += 1

                # 에이전트 응답 대기
                self.waiting_for_response = True
                self._response_event.clear()
                self._pending_messages.clear()

                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    print(f"[TestUser] 에이전트 응답 타임아웃 ({IDLE_TIMEOUT}초)")
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

        elapsed = time.time() - self._test_start_time
        print(f"\n[TestUser] 테스트 종료 — {self.turn_count}턴, {elapsed:.0f}초")
        print(f"[TestUser] 대화 기록 {len(self.conversation)}건")
        await asyncio.sleep(2)
        await self.close()

    async def _generate_reply(self) -> str:
        """Claude CLI로 테스트 유저 응답 생성"""
        # 최근 대화 맥락 구성
        context_lines = []
        for msg in self.conversation[-15:]:
            prefix = "나" if msg["role"] == "user" else msg["name"]
            context_lines.append(f"{prefix}: {msg['text']}")
        context = "\n".join(context_lines)

        prompt = (
            f"대화 기록:\n{context}\n\n"
            f"위 대화를 보고 다음 답장을 해. "
            f"카톡처럼 짧게 1~3문장. 줄바꿈으로 메시지 구분. "
            f"자연스럽게."
        )

        try:
            result = subprocess.run(
                [
                    "claude", "-p", prompt,
                    "--system-prompt", PERSONA,
                    "--output-format", "text",
                    "--model", "claude-haiku-4-5-20251001",
                ],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            else:
                print(f"[TestUser] Claude 오류: {result.stderr[:100]}")
                return ""
        except subprocess.TimeoutExpired:
            print("[TestUser] Claude 타임아웃")
            return ""
        except FileNotFoundError:
            print("[TestUser] claude CLI 없음")
            return ""

    async def _send_reply(self, reply: str):
        """응답을 디스코드에 전송"""
        lines = [l.strip() for l in reply.strip().split("\n") if l.strip()]

        # 자기 이름 prefix 제거
        cleaned = []
        for line in lines:
            if line.startswith("나:") or line.startswith(f"{_QA_NAME}:"):
                line = line.split(":", 1)[1].strip()
            if line:
                cleaned.append(line)

        if not cleaned:
            return

        # 일정 확률로 메시지를 따로 보냄 (카톡 스타일)
        if len(cleaned) > 1 and random.random() < MULTI_MSG_CHANCE:
            for line in cleaned:
                await self.target_channel.send(line)
                self.conversation.append({"role": "user", "name": _QA_NAME, "text": line})
                print(f"[{_QA_NAME}] {line}")
                await asyncio.sleep(random.uniform(0.5, 1.5))
        else:
            text = "\n".join(cleaned)
            await self.target_channel.send(text)
            self.conversation.append({"role": "user", "name": _QA_NAME, "text": text})
            print(f"[{_QA_NAME}] {text}")

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
