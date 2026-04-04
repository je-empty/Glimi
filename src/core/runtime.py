"""
에이전트 런타임: Claude Code CLI subagent를 통해 에이전트 응답 생성

사용 방식:
  - Claude Code Max 플랜의 `claude` CLI를 subprocess로 호출
  - 각 에이전트별 system prompt + 대화 이력을 주입
  - claude CLI가 없으면 자동으로 placeholder 모드로 전환

응답 모드:
  - generate_response: 기존 방식 (전체 응답 수집 후 반환)
  - generate_response_streaming: 스트리밍 (줄 단위로 on_message 콜백 호출)
"""
import re
import json
import subprocess
import shutil
import os
from typing import Optional, Callable
from src import db
from .profile import load_profile, build_system_prompt, get_user_name, get_user_id
from .memory import check_and_summarize, get_memory_context, get_cross_channel_memory, RAW_WINDOW
from src import log_writer


def _check_claude_cli() -> bool:
    return shutil.which("claude") is not None


CLAUDE_AVAILABLE = _check_claude_cli()

AGENT_MODELS = {
    "persona": "claude-sonnet-4-6",
    "mgr": "claude-sonnet-4-6",
    "creator": "claude-sonnet-4-6",  # 일반 대화는 sonnet, 심화 작업은 discord_bot에서 opus 직접 지정
}
OPUS_MODEL = "claude-opus-4-6"


def _normalize(s):
    return re.sub(r'[.?!,~\s…·ㅋㅎㅠ]', '', s).lower()


class AgentRuntime:

    def __init__(self):
        self._active_agents: dict[str, dict] = {}

        if CLAUDE_AVAILABLE:
            print("[Runtime] Claude Code CLI 감지됨 — 실제 대화 모드")
        else:
            print("[Runtime] Claude Code CLI 미감지 — placeholder 모드")
            print("[Runtime]   설치: npm install -g @anthropic-ai/claude-code")

    def activate_agent(self, agent_id: str) -> bool:
        profile = load_profile(agent_id)
        if not profile:
            return False

        system_prompt = build_system_prompt(agent_id)
        self._active_agents[agent_id] = {
            "profile": profile,
            "system_prompt": system_prompt,
        }
        print(f"[Runtime] {profile['name']} ({agent_id}) 활성화")
        return True

    def get_active_agents(self) -> list[str]:
        return list(self._active_agents.keys())

    def get_agent_name(self, agent_id: str) -> str:
        if agent_id in self._active_agents:
            return self._active_agents[agent_id]["profile"]["name"]
        profile = load_profile(agent_id)
        return profile["name"] if profile else agent_id

    # ── Prompt building ──────────────────────────────

    def _build_context(self, agent_info: dict, channel: str, recent: list[dict]) -> str:
        """에이전트 맥락 구성 (감정 + 메모리 + 대화이력). 마지막 발화는 포함하지 않음."""
        profile = agent_info["profile"]
        agent_id = profile["id"]
        agent_type = profile.get("type", "persona")

        prompt_parts = []

        # 현재 감정
        agent_state = db.get_agent(agent_id)
        if agent_state:
            prompt_parts.append(
                f"[현재감정: {agent_state['current_emotion']}"
                f"({agent_state['emotion_intensity']}/10)]"
            )

        # 유나(mgr)에게는 실시간 활동 요약 자동 주입
        if agent_type == "mgr":
            digest = self._build_activity_digest()
            if digest:
                prompt_parts.append(digest)

        # ── 기억 섹션 ──
        memory_text = get_memory_context(agent_id, channel)
        cross_memory = get_cross_channel_memory(agent_id, exclude_channel=channel)

        if memory_text or cross_memory:
            prompt_parts.append("━━━ 기억 ━━━")

        if memory_text:
            prompt_parts.append(memory_text)

        if cross_memory:
            if memory_text:
                prompt_parts.append("")
            prompt_parts.append(cross_memory)

        if memory_text or cross_memory:
            prompt_parts.append("━━━━━━━━━━━")

        # ── 다른 채널 최근 대화 (요약 없이 직접 주입) ──
        cross_recent = self._get_cross_channel_recent(agent_id, channel)
        if cross_recent:
            prompt_parts.append(cross_recent)

        # 대화 이력 — mgr 채널은 유저 메시지가 묻히지 않게 보장
        if recent:
            if prompt_parts:
                prompt_parts.append("")

            if agent_type == "mgr" and (channel.startswith("mgr-") or channel.startswith("dm-")):
                # mgr/dm 채널에서만 유저 메시지 + 직전 유나 응답만 (유나 보고 반복 방지)
                # internal- 채널(에이전트간 대화)에서는 전체 이력 필요
                filtered = []
                for msg in recent:
                    if msg["speaker"] == get_user_id():
                        filtered.append(msg)
                    elif len(filtered) == 0 or filtered[-1]["speaker"] == get_user_id():
                        # 유저 메시지 바로 다음 유나 응답만 포함
                        filtered.append(msg)
                for msg in filtered[-15:]:
                    speaker = get_user_name() if msg["speaker"] == get_user_id() else self.get_agent_name(msg["speaker"])
                    prompt_parts.append(f"{speaker}: {msg['message']}")
            else:
                for msg in recent:
                    speaker = get_user_name() if msg["speaker"] == get_user_id() else self.get_agent_name(msg["speaker"])
                    prompt_parts.append(f"{speaker}: {msg['message']}")
            prompt_parts.append("")

        return "\n".join(prompt_parts)

    def _build_prompt(self, agent_info: dict, channel: str, recent: list[dict],
                      user_message: str, speaker_name: str = "") -> tuple[str, str, str]:
        """프롬프트 구성. Returns: (full_prompt, system_prompt, model)
        speaker_name: 마지막 발화자 이름 (빈 문자열이면 유저 이름 사용)
        """
        context = self._build_context(agent_info, channel, recent)
        name = speaker_name or get_user_name()
        full_prompt = context + f"{name}: {user_message}"

        system_prompt = agent_info["system_prompt"]
        model = AGENT_MODELS.get(agent_info["profile"].get("type", "persona"), "claude-sonnet-4-6")

        return full_prompt, system_prompt, model

    def _get_cross_channel_recent(self, agent_id: str, current_channel: str) -> str:
        """다른 채널 근황 — 요약 없는 채널만 마지막 메시지 1줄로 보충

        요약(L1/L2)이 있는 채널은 cross_channel_memory가 이미 커버.
        여기서는 요약이 아직 없는 짧은 대화만 한줄로 보여줌.
        """
        conn = db.get_conn()

        # 이 에이전트가 참여한 채널 (현재 채널 + mgr 제외)
        channels = conn.execute(
            """SELECT channel, MAX(id) as last_id FROM conversations
               WHERE speaker = ? AND channel != ? AND channel NOT LIKE 'mgr%'
               GROUP BY channel
               ORDER BY last_id DESC""",
            (agent_id, current_channel)
        ).fetchall()

        if not channels:
            conn.close()
            return ""

        # 요약이 커버하는 마지막 메시지 ID 확인
        mem_coverage = {}  # channel → last covered msg_id
        mem_rows = conn.execute(
            "SELECT channel, MAX(msg_id_to) as last_covered FROM memories WHERE agent_id = ? AND channel != ? GROUP BY channel",
            (agent_id, current_channel)
        ).fetchall()
        for r in mem_rows:
            mem_coverage[r["channel"]] = r["last_covered"] or 0
        conn.close()

        lines = []
        for ch_row in channels:
            ch_name = ch_row["channel"]
            last_covered = mem_coverage.get(ch_name, 0)

            # 이 채널의 최신 메시지가 요약 범위 안이면 스킵
            if ch_row["last_id"] <= last_covered:
                continue

            recent = db.get_recent_messages(ch_name, limit=1)
            if not recent:
                continue

            r = recent[0]
            speaker = get_user_name() if r["speaker"] == get_user_id() else self.get_agent_name(r["speaker"])
            preview = r["message"][:40]

            # 채널 라벨
            if ch_name.startswith("dm-"):
                label = f"{get_user_name()}과 DM"
            elif ch_name.startswith("internal-dm-"):
                names = ch_name.replace("internal-dm-", "").split("-")
                other = [n for n in names if n != self.get_agent_name(agent_id)]
                label = f"{other[0] if other else names[0]}과 대화" if other else ch_name
            elif ch_name.startswith("internal-group-"):
                names = ch_name.replace("internal-group-", "")
                label = f"{names} 단톡"
            elif ch_name.startswith("group-"):
                names = ch_name.replace("group-", "")
                label = f"{names} 톡방"
            else:
                label = ch_name

            lines.append(f"- {label}: {speaker}→\"{preview}\"")

        if not lines:
            return ""
        return "[최근 다른 대화]\n" + "\n".join(lines)

    def _build_activity_digest(self) -> str:
        """유나 전용: 최근 활동 요약 (토큰 절약형, ~100-150 토큰)"""
        lines = []

        # 최근 활성 채널 + 마지막 메시지 요약
        overview = db.get_channel_overview()
        active = []
        for ch in overview:
            from datetime import datetime
            try:
                last = datetime.fromisoformat(ch["last_active"])
                mins = (datetime.now() - last).total_seconds() / 60
            except Exception:
                mins = 9999

            if mins < 30:  # 30분 이내 활성
                active.append((ch["channel"], ch["msg_count"], int(mins)))

        if active:
            lines.append("[최근 활동]")
            for ch_name, cnt, mins_ago in active[:8]:
                # 채널의 최근 메시지 1줄만
                recent = db.get_recent_messages(ch_name, limit=1)
                if recent:
                    r = recent[0]
                    speaker = get_user_name() if r["speaker"] == get_user_id() else self.get_agent_name(r["speaker"])
                    msg_preview = r["message"][:30]
                    lines.append(f"  {ch_name}({mins_ago}분전): {speaker}→\"{msg_preview}\"")
                else:
                    lines.append(f"  {ch_name}({mins_ago}분전, {cnt}건)")

        # 현재 진행중인 내부 대화
        from src import log_writer
        thinking = []
        for aid, info in self._active_agents.items():
            if log_writer.is_thinking(aid) and info["profile"].get("type") == "persona":
                thinking.append(info["profile"]["name"])
        if thinking:
            lines.append(f"[추론중] {', '.join(thinking)}")

        # 감정 변화가 큰 멤버 (강도 7 이상)
        high_emotion = []
        for a in db.list_agents("persona"):
            if a["emotion_intensity"] >= 7:
                high_emotion.append(f"{a['name']}:{a['current_emotion']}({a['emotion_intensity']})")
        if high_emotion:
            lines.append(f"[감정주의] {', '.join(high_emotion)}")

        return "\n".join(lines) if lines else ""

    # ── Force mode ────────────────────────────────────

    def generate_response_force(self, agent_id: str, channel: str,
                                user_message: str) -> list[str]:
        """강제 지시 — 시스템 프롬프트에 강제 지시 추가, user_message는 순수 질문만"""
        if agent_id not in self._active_agents:
            self.activate_agent(agent_id)
        if agent_id not in self._active_agents:
            return ["[오류] 에이전트를 찾을 수 없습니다."]

        agent_info = self._active_agents[agent_id]
        profile = agent_info["profile"]
        _limit = 50 if profile.get("type") == "mgr" else RAW_WINDOW
        recent = db.get_recent_messages(channel, limit=_limit)

        log_writer.mark_thinking(agent_id)
        log_writer.agent_thinking(agent_id, f"강제 지시 [{channel}]: {user_message[:40]}")

        try:
            # 시스템 프롬프트에 짧은 행동 트리거만 주입
            base_system = agent_info["system_prompt"]
            force_system = (
                "####### 지금 너는 이렇게 하고 싶다 #######\n"
                f"→ {user_message}\n"
                "이건 네 안에서 자연스럽게 든 생각이야. 망설이지 말고 바로 행동해.\n"
                "기억에 관련 맥락이 있으면 살려서 자연스럽게.\n"
                "########################################\n\n"
                + base_system
            )

            # 전체 맥락 (감정 + 메모리 + cross-channel + 대화이력) + 트리거
            context = self._build_context(agent_info, channel, recent)
            full_prompt = context + "(자연스럽게 먼저 말 걸어)"

            model = AGENT_MODELS.get(profile.get("type", "persona"), "claude-sonnet-4-6")

            result = subprocess.run(
                [
                    "claude",
                    "-p", full_prompt,
                    "--system-prompt", force_system,
                    "--output-format", "text",
                    "--model", model,
                ],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
            )

            if result.returncode != 0:
                return self._placeholder_response(profile, user_message)

            raw = result.stdout.strip()
            if not raw:
                return ["..."]

            responses = self._parse_response(raw, agent_name=profile["name"])

        except Exception as e:
            log_writer.system(f"❌ 강제 지시 오류: {e}")
            responses = self._placeholder_response(profile, user_message)
        finally:
            log_writer.mark_done(agent_id)

        # DB 로깅 (에이전트 응답만)
        agent_db = db.get_agent(agent_id)
        current_emotion = agent_db.get("current_emotion", "평온") if agent_db else None
        for msg in responses:
            db.log_message(channel, agent_id, msg, emotion=current_emotion)

        return responses

    # ── Non-streaming (backward compat) ──────────────

    def generate_response(self, agent_id: str, channel: str, user_message: str,
                          log_user_message: bool = True, model_override: str = "") -> list[str]:
        """
        에이전트 응답 생성 (배치 모드)
        model_override: 특정 모델 강제 지정 (빈 문자열이면 기본 모델)
        """
        if agent_id not in self._active_agents:
            self.activate_agent(agent_id)
        if agent_id not in self._active_agents:
            return ["[오류] 에이전트를 찾을 수 없습니다."]

        agent_info = self._active_agents[agent_id]
        profile = agent_info["profile"]
        if model_override:
            self._model_override = model_override
        _limit = 50 if profile.get("type") == "mgr" else RAW_WINDOW
        recent = db.get_recent_messages(channel, limit=_limit)

        log_writer.mark_thinking(agent_id)
        log_writer.agent_thinking(agent_id, f"응답 생성 시작 [{channel}]")

        try:
            if CLAUDE_AVAILABLE:
                responses = self._call_claude_code(agent_info, channel, recent, user_message)
            else:
                responses = self._placeholder_response(profile, user_message)
        finally:
            log_writer.mark_done(agent_id)

        log_writer.agent_thinking(agent_id, f"응답 {len(responses)}건")

        # 로깅
        if log_user_message:
            db.log_message(channel, get_user_id(), user_message)
            log_writer.chat(channel, get_user_name(), user_message)

        agent_db = db.get_agent(agent_id)
        current_emotion = agent_db.get("current_emotion", "평온") if agent_db else None
        for msg in responses:
            db.log_message(channel, agent_id, msg, emotion=current_emotion)

        try:
            check_and_summarize(agent_id, channel)
        except Exception as e:
            print(f"[Memory] 요약 체크 오류 (무시): {e}")

        return responses

    def _call_claude_code(self, agent_info: dict, channel: str,
                          recent: list[dict], user_message: str) -> list[str]:
        """Claude CLI 호출 (블로킹)"""
        profile = agent_info["profile"]
        name = profile["name"]
        agent_id = profile["id"]

        full_prompt, system_prompt, model = self._build_prompt(
            agent_info, channel, recent, user_message
        )

        # model override 체크
        if hasattr(self, '_model_override') and self._model_override:
            model = self._model_override
            self._model_override = ""

        log_writer.agent_thinking(agent_id, f"Claude CLI 호출 ({model})")

        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p", full_prompt,
                    "--system-prompt", system_prompt,
                    "--output-format", "text",
                    "--model", model,
                ],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
            )

            if result.returncode != 0:
                log_writer.system(f"❌ CLI 오류: {result.stderr[:200]}")
                return self._placeholder_response(profile, user_message)

            raw = result.stdout.strip()
            if not raw:
                return ["..."]

            # Raw CLI 출력 로깅
            for line in raw.split("\n"):
                line = line.strip()
                if line:
                    log_writer.agent_thinking(agent_id, line)

            return self._parse_response(raw, agent_name=name)

        except subprocess.TimeoutExpired:
            log_writer.system(f"❌ CLI 타임아웃 (60초)")
            return [f"({name} 응답 지연 — 다시 시도해주세요)"]
        except FileNotFoundError:
            print("[Runtime] claude CLI를 찾을 수 없습니다")
            return self._placeholder_response(profile, user_message)
        except Exception as e:
            log_writer.system(f"❌ 런타임 오류: {e}")
            return self._placeholder_response(profile, user_message)

    # ── Streaming ────────────────────────────────────

    def generate_response_streaming(
        self, agent_id: str, channel: str, user_message: str,
        on_message: Callable[[str], None],
        log_user_message: bool = True,
    ) -> list[str]:
        """
        스트리밍 응답 생성 — 메시지가 생성될 때마다 on_message 콜백 호출

        on_message는 동기 함수 (discord_bot이 loop.call_soon_threadsafe로 감쌈)
        Returns: 전체 메시지 리스트 (DB 로깅용)
        """
        if agent_id not in self._active_agents:
            self.activate_agent(agent_id)
        if agent_id not in self._active_agents:
            on_message("[오류] 에이전트를 찾을 수 없습니다.")
            return ["[오류] 에이전트를 찾을 수 없습니다."]

        agent_info = self._active_agents[agent_id]
        profile = agent_info["profile"]
        name = profile["name"]
        _limit = 50 if profile.get("type") == "mgr" else RAW_WINDOW
        recent = db.get_recent_messages(channel, limit=_limit)

        # 유저 메시지 먼저 로깅
        if log_user_message:
            db.log_message(channel, get_user_id(), user_message)
            log_writer.chat(channel, get_user_name(), user_message)

        log_writer.mark_thinking(agent_id)
        log_writer.agent_thinking(agent_id, f"응답 생성 시작 [{channel}]")

        if not CLAUDE_AVAILABLE:
            log_writer.mark_done(agent_id)
            msgs = self._placeholder_response(profile, user_message)
            for m in msgs:
                on_message(m)
            return msgs

        full_prompt, system_prompt, model = self._build_prompt(
            agent_info, channel, recent, user_message
        )

        log_writer.agent_thinking(agent_id, f"Claude CLI 호출 ({model})")

        messages = []
        seen = set()

        try:
            process = subprocess.Popen(
                [
                    "claude",
                    "-p", full_prompt,
                    "--system-prompt", system_prompt,
                    "--output-format", "text",
                    "--model", model,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
            )

            for line in process.stdout:
                raw_line = line.rstrip("\n")
                if raw_line.strip():
                    # Raw CLI 출력 그대로 로깅
                    log_writer.agent_thinking(agent_id, raw_line)

                line = raw_line.strip()
                if not line:
                    continue

                # [MSG] 태그 처리
                line = line.replace("[MSG]", "")
                cleaned = " ".join(line.split())
                if not cleaned:
                    continue

                # 자기 이름 prefix 제거 ("윤하나: 메시지" → "메시지")
                if cleaned.startswith(f"{name}:"):
                    cleaned = cleaned[len(name)+1:].strip()
                elif cleaned.startswith(f"{name} :"):
                    cleaned = cleaned[len(name)+2:].strip()
                if not cleaned:
                    continue

                # 실시간 중복 체크 (exact match)
                key = _normalize(cleaned)
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)

                messages.append(cleaned)
                on_message(cleaned)

            process.wait(timeout=60)

            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else ""
                log_writer.system(f"❌ CLI stderr: {stderr[:200]}")
                if not messages:
                    fallback = self._placeholder_response(profile, user_message)
                    for m in fallback:
                        on_message(m)
                    messages = fallback

        except subprocess.TimeoutExpired:
            process.kill()
            log_writer.system(f"❌ CLI 타임아웃 (60초)")
            if not messages:
                msg = f"({name} 응답 지연 — 다시 시도해주세요)"
                on_message(msg)
                messages = [msg]
        except Exception as e:
            log_writer.system(f"❌ 런타임 오류: {e}")
            if not messages:
                fallback = self._placeholder_response(profile, user_message)
                for m in fallback:
                    on_message(m)
                messages = fallback
        finally:
            log_writer.mark_done(agent_id)
            log_writer.agent_thinking(agent_id, f"응답 완료 {len(messages)}건")

        # DB 로깅
        agent_db = db.get_agent(agent_id)
        current_emotion = agent_db.get("current_emotion", "평온") if agent_db else None
        for msg in messages:
            db.log_message(channel, agent_id, msg, emotion=current_emotion)

        try:
            check_and_summarize(agent_id, channel)
        except Exception as e:
            print(f"[Memory] 요약 체크 오류 (무시): {e}")

        return messages

    # ── Response parsing ─────────────────────────────

    def _parse_response(self, raw: str, agent_name: str = "") -> list[str]:
        if not raw:
            return ["..."]

        raw = raw.replace("[MSG]", "\n")
        lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        if not lines:
            return ["..."]

        messages = []
        for line in lines:
            cleaned = " ".join(line.split())
            if not cleaned:
                continue
            # 자기 이름 prefix 제거
            if agent_name and cleaned.startswith(f"{agent_name}:"):
                cleaned = cleaned[len(agent_name)+1:].strip()
            elif agent_name and cleaned.startswith(f"{agent_name} :"):
                cleaned = cleaned[len(agent_name)+2:].strip()
            if cleaned:
                messages.append(cleaned)

        if not messages:
            return ["..."]

        # 중복 제거 (exact + substring)
        unique = []
        seen = set()
        for msg in messages:
            key = _normalize(msg)
            if not key:
                unique.append(msg)
                continue
            if key in seen:
                continue
            is_subset = False
            for existing in unique:
                if key in _normalize(existing):
                    is_subset = True
                    break
            if is_subset:
                continue
            seen.add(key)
            unique.append(msg)

        return unique if unique else ["..."]

    def _placeholder_response(self, profile: dict, user_message: str) -> list[str]:
        name = profile["name"]
        agent_type = profile.get("type", "persona")

        # 사용자 호칭: relationship_to_owner.pet_name → user name → 기본값
        rel = profile.get("relationship_to_owner", {})
        owner_call = rel.get("pet_name") or get_user_name() or "사용자"

        if agent_type == "mgr":
            return [
                f"{owner_call} 나 {name}인데",
                "지금 Claude Code 연결이 끊겨서 추론이 안 돼",
                "연결 복구되면 바로 할게"
            ]
        elif agent_type == "creator":
            return [
                f"{owner_call} 나 {name}~",
                "Claude Code 연결 끊겨서 지금은 작업 못 해 ㅠ"
            ]
        else:
            speech = profile.get("speech", {})
            exprs = speech.get("signature_expressions", [])
            sample = exprs[0] if exprs else "응"
            return [
                f"{owner_call} {sample}",
                f"나 {name}인데 지금 Claude Code 연결이 끊겨있어",
            ]

    def refresh_agent(self, agent_id: str):
        if agent_id in self._active_agents:
            self._active_agents[agent_id]["system_prompt"] = build_system_prompt(agent_id)
            print(f"[Runtime] {agent_id} prompt 갱신")

    # ── 에이전트 간 대화 ─────────────────────────────

    def generate_agent_to_agent(
        self, speaker_id: str, listener_id: str, channel: str, context: str = ""
    ) -> list[str]:
        for aid in (speaker_id, listener_id):
            if aid not in self._active_agents:
                self.activate_agent(aid)

        speaker_info = self._active_agents.get(speaker_id)
        listener_info = self._active_agents.get(listener_id)

        if not speaker_info or not listener_info:
            return ["[오류] 에이전트 로드 실패"]

        speaker_name = speaker_info["profile"]["name"]
        listener_name = listener_info["profile"]["name"]

        recent = db.get_recent_messages(channel, limit=RAW_WINDOW)

        # _build_context 재활용 (speaker 기준 메모리)
        base_context = self._build_context(speaker_info, channel, recent)

        if context:
            full_prompt = base_context + f"상황: {context}\n{listener_name}과(와)의 대화를 이어가."
        else:
            full_prompt = base_context + f"{listener_name}과(와)의 대화를 이어가."

        speaker_type = speaker_info["profile"].get("type", "persona")
        model = AGENT_MODELS.get(speaker_type, "claude-sonnet-4-6")

        log_writer.mark_thinking(speaker_id)
        try:
            if CLAUDE_AVAILABLE:
                try:
                    result = subprocess.run(
                        [
                            "claude",
                            "-p", full_prompt,
                            "--system-prompt", speaker_info["system_prompt"],
                            "--output-format", "text",
                            "--model", model,
                        ],
                        capture_output=True, text=True, timeout=60,
                        env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        responses = self._parse_response(result.stdout.strip(), agent_name=speaker_name)
                        for msg in responses:
                            db.log_message(channel, speaker_id, msg)

                        # 에이전트간 대화 — 양쪽 모두 메모리 요약 트리거
                        try:
                            check_and_summarize(speaker_id, channel)
                        except Exception as e:
                            print(f"[Memory] 요약 오류 ({speaker_id}): {e}")
                        try:
                            check_and_summarize(listener_id, channel)
                        except Exception as e:
                            print(f"[Memory] 요약 오류 ({listener_id}): {e}")

                        return responses
                except Exception as e:
                    log_writer.system(f"❌ 에이전트간 대화 오류: {e}")

            return [f"[테스트] {speaker_name}→{listener_name}: (Claude Code 연동 후 동작)"]
        finally:
            log_writer.mark_done(speaker_id)


# 싱글턴
runtime = AgentRuntime()
