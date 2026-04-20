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
from .profile import load_profile, build_system_prompt, get_user_name, get_user_id, get_user_display_name
from .memory import check_and_summarize, get_memory_context, RAW_WINDOW
from .tools import parse_response as parse_tools_in_output, ToolCall
from src import log_writer


def _check_claude_cli() -> bool:
    return shutil.which("claude") is not None


CLAUDE_AVAILABLE = _check_claude_cli()

AGENT_MODELS = {
    "persona": "claude-sonnet-4-6",
    "mgr": "claude-sonnet-4-6",
    "creator": "claude-sonnet-4-6",  # 대화는 소넷
}
AGENT_TASK_MODELS = {
    "creator": "claude-opus-4-6",  # 프로필 JSON 생성은 opus
}

# 대시보드에서 선택 가능한 모델 카탈로그.
# Phase 1: 클라우드(Claude) 모델만. Phase 2 에서 로컬 모델 (ollama/vllm 등) 여러 종 추가.
# kind: "cloud" | "local" — UI 에서 ☁️/🖥️ 아이콘으로 구분.
# provider: "claude" | "ollama" | "vllm" | "llamacpp" — 백엔드 선택에도 사용.
AVAILABLE_MODELS = [
    {"id": "claude-sonnet-4-6", "label": "Sonnet 4.6",
     "kind": "cloud", "provider": "claude", "tier": "balanced", "icon": "☁️"},
    {"id": "claude-haiku-4-5", "label": "Haiku 4.5",
     "kind": "cloud", "provider": "claude", "tier": "fast", "icon": "☁️"},
    # Phase 2 로컬 모델 예시 (주석 — 실제 구현 시 해제 + src/llm/local.py 추가):
    # {"id": "ollama:llama3.3:8b", "label": "Llama 3.3 8B",
    #  "kind": "local", "provider": "ollama", "tier": "fast", "icon": "🖥️"},
    # {"id": "ollama:qwen2.5:14b", "label": "Qwen 2.5 14B",
    #  "kind": "local", "provider": "ollama", "tier": "balanced", "icon": "🖥️"},
    # {"id": "vllm:mistral-small-3", "label": "Mistral Small 3",
    #  "kind": "local", "provider": "vllm", "tier": "balanced", "icon": "🖥️"},
]


def _resolve_agent_model(agent_id: str, agent_type: str) -> str:
    """실효 모델 결정 — DB override 우선, 없으면 AGENT_MODELS[type] 기본값.
    매 호출마다 조회 → 대시보드에서 변경 시 즉시 반영 (재시작 불필요).
    컨텍스트 연속성: 대화 이력·메모리는 DB 기반이라 모델 바뀌어도 그대로 이어감."""
    try:
        override = db.get_agent_model_override(agent_id)
        if override:
            return override
    except Exception:
        pass
    return AGENT_MODELS.get(agent_type, "claude-sonnet-4-6")
OPUS_MODEL = "claude-opus-4-6"


def _normalize(s):
    return re.sub(r'[.?!,~\s…·ㅋㅎㅠ]', '', s).lower()


# Claude CLI가 stdout으로 토해내는 에러/상태 메시지 패턴.
# 이게 agent 응답인 척 DB/Discord에 찍히면 몰입 깨지므로 필터.
_CLAUDE_ERROR_PREFIXES = (
    "you've hit your limit",
    "you have hit your limit",
    "your usage limit",
    "usage limit",
    "rate limit exceeded",
    "anthropic api error",
    "anthropic error",
    "api error:",
    "request was too large",
    "insufficient credits",
    "service unavailable",
    "too many requests",
    "context length exceeded",
    "overloaded_error",
    "internal server error",
    "bad gateway",
    "gateway timeout",
    "claude api",
    "model not found",
    "authentication",
)


def _looks_like_claude_error(text: str) -> bool:
    """Claude CLI 에러 메시지가 agent 응답으로 새어나오는 케이스 감지."""
    if not text:
        return False
    t = text.strip().lower()
    if not t:
        return False
    for p in _CLAUDE_ERROR_PREFIXES:
        if t.startswith(p) or p in t[:80]:  # 첫 80자 내 포함도 체크
            return True
    # "resets <time>" 패턴 (사용량 한도 도달 메시지 후반부)
    if "resets" in t and ("am" in t or "pm" in t or ":" in t):
        if "limit" in t or "reset" in t:
            return True
    return False


def _report_claude_error(agent_name: str, text: str, source: str):
    """에러 텍스트 필터링 시 system.log + Discord mgr-system-log 양쪽에 남김."""
    snippet = text.strip().replace("\n", " ")[:200]
    msg = f"⚠ Claude CLI 에러 필터 [{agent_name}/{source}]: {snippet}"
    log_writer.system(msg)
    # Discord mgr-system-log 채널에도 송출 (bot 모듈 임포트는 lazy — 순환 방지)
    try:
        from src.bot.core import queue_system_log
        queue_system_log(msg, force=True)
    except Exception:
        pass


class AgentRuntime:

    def __init__(self):
        self._active_agents: dict[str, dict] = {}
        # 최근 응답에서 추출한 tool_calls 저장소 (key=agent_id, consume 후 삭제)
        self._last_tool_calls: dict[str, list[ToolCall]] = {}
        # 다음 호출 시 prompt에 주입할 <tool_results> 블록 (key=agent_id:channel)
        self._pending_tool_results: dict[str, str] = {}

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
        from .profile import get_agent_display_name
        return get_agent_display_name(agent_id)

    # ── Prompt building ──────────────────────────────

    def _build_context(self, agent_info: dict, channel: str, recent: list[dict],
                       user_message: str = "") -> str:
        """에이전트 맥락 구성 (채널 정보 + 감정 + 메모리 + 대화이력)."""
        import time as _time
        _t = _time.monotonic()
        def _checkpoint(label):
            nonlocal _t
            now = _time.monotonic()
            dt = now - _t
            if dt > 5.0:
                log_writer.system(f"⏱ _build_context[{label}] {dt:.1f}s")
            _t = now

        profile = agent_info["profile"]
        agent_id = profile["id"]
        agent_type = profile.get("type", "persona")

        prompt_parts = []
        reminder_parts = []  # <system-reminder>로 감쌀 동적 컨텍스트

        # 채널 정보 (고정 정보지만 context 특정)
        ch_info = self._describe_channel(channel, agent_id)
        if ch_info:
            reminder_parts.append(ch_info)
        _checkpoint("describe_channel")

        # 현재 감정 (dynamic)
        agent_state = db.get_agent(agent_id)
        if agent_state:
            reminder_parts.append(
                f"[현재감정: {agent_state['current_emotion']}"
                f"({agent_state['emotion_intensity']}/10)]"
            )

        # 유나(mgr)에게는 실시간 활동 요약 자동 주입
        if agent_type == "mgr":
            digest = self._build_activity_digest()
            if digest:
                reminder_parts.append(digest)
            _checkpoint("activity_digest")

        # ── 기억 섹션 (5 레이어 통합) ──
        # user_message + 최근 대화 텍스트를 entity 매칭용 힌트로 넘김
        focus_hint = user_message + "\n" + "\n".join(m.get("message", "") for m in recent[-5:])
        memory_text = get_memory_context(agent_id, channel, user_message=focus_hint)
        _checkpoint("memory_context")

        if memory_text:
            reminder_parts.append("━━━ 기억 ━━━\n" + memory_text + "\n━━━━━━━━━━━")

        # ── 다른 채널 최근 대화 (요약 없이 직접 주입) ──
        cross_recent = self._get_cross_channel_recent(agent_id, channel)
        if cross_recent:
            reminder_parts.append(cross_recent)
        _checkpoint("cross_channel_recent")

        # 동적 컨텍스트 전체를 system-reminder로 감싸기
        if reminder_parts:
            prompt_parts.append("<system-reminder>")
            prompt_parts.extend(reminder_parts)
            prompt_parts.append("</system-reminder>")

        # 대화 이력 — mgr 채널은 오너 메시지가 묻히지 않게 보장
        if recent:
            if prompt_parts:
                prompt_parts.append("")

            if agent_type == "mgr" and (channel.startswith("mgr-") or channel.startswith("dm-")):
                # mgr/dm 채널에서만 오너 메시지 + 직전 유나 응답만 (유나 보고 반복 방지)
                # internal- 채널(에이전트간 대화)에서는 전체 이력 필요
                filtered = []
                for msg in recent:
                    if msg["speaker"] == get_user_id():
                        filtered.append(msg)
                    elif len(filtered) == 0 or filtered[-1]["speaker"] == get_user_id():
                        # 오너 메시지 바로 다음 유나 응답만 포함
                        filtered.append(msg)
                for msg in filtered[-15:]:
                    speaker = get_user_display_name() if msg["speaker"] == get_user_id() else self.get_agent_name(msg["speaker"])
                    prompt_parts.append(f"{speaker}: {msg['message']}")
            else:
                for msg in recent:
                    speaker = get_user_display_name() if msg["speaker"] == get_user_id() else self.get_agent_name(msg["speaker"])
                    prompt_parts.append(f"{speaker}: {msg['message']}")
            prompt_parts.append("")

        return "\n".join(prompt_parts)

    def pop_tool_calls(self, agent_id: str) -> list[ToolCall]:
        """generate_response 이후 마지막 tool_calls 꺼내서 소비 (재호출 시 덮어씀)"""
        calls = self._last_tool_calls.pop(agent_id, [])
        return calls

    def stash_tool_results(self, agent_id: str, channel: str, results_block: str):
        """다음 generate_response 호출 시 prompt에 주입될 <tool_results> 블록 저장"""
        key = f"{agent_id}:{channel}"
        if results_block:
            self._pending_tool_results[key] = results_block
        else:
            self._pending_tool_results.pop(key, None)

    def _consume_tool_results(self, agent_id: str, channel: str) -> str:
        """stash된 tool_results 꺼내고 제거"""
        key = f"{agent_id}:{channel}"
        return self._pending_tool_results.pop(key, "")

    def _build_prompt(self, agent_info: dict, channel: str, recent: list[dict],
                      user_message: str, speaker_name: str = "") -> tuple[str, str, str]:
        """프롬프트 구성. Returns: (full_prompt, system_prompt, model)"""
        agent_id = agent_info["profile"]["id"]
        context = self._build_context(agent_info, channel, recent, user_message=user_message)

        # 이전 턴의 tool_results가 있으면 user_message 앞에 주입
        tool_results = self._consume_tool_results(agent_id, channel)
        name = speaker_name or get_user_display_name()
        if tool_results:
            full_prompt = context + tool_results + "\n\n" + f"{name}: {user_message}"
        else:
            full_prompt = context + f"{name}: {user_message}"

        system_prompt = agent_info["system_prompt"]
        model = _resolve_agent_model(agent_id, agent_info["profile"].get("type", "persona"))

        return full_prompt, system_prompt, model

    def _build_handoff_summary(self, agent_id: str, channel: str) -> str:
        """모델 전환 시 이전 대화 맥락 요약 생성 (haiku로 빠르게)"""
        recent = db.get_recent_messages(channel, limit=15)
        if not recent:
            return ""

        lines = []
        for r in recent:
            speaker = get_user_display_name() if r["speaker"] == get_user_id() else self.get_agent_name(r["speaker"])
            lines.append(f"{speaker}: {r['message']}")
        conversation = "\n".join(lines[-10:])

        try:
            result = subprocess.run(
                ["claude", "-p",
                 f"아래 대화를 3~4문장으로 요약해. 누가 뭘 요청했고 어디까지 진행됐는지 핵심만:\n\n{conversation}",
                 "--output-format", "text", "--model", "claude-haiku-4-5"],
                capture_output=True, text=True, timeout=15,
                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"[이전 대화 요약] {result.stdout.strip()}"
        except Exception:
            pass

        # haiku 실패 시 최근 3턴만 직접 포함
        return "[이전 대화 (최근)] " + " / ".join(lines[-3:])

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
            speaker = get_user_display_name() if r["speaker"] == get_user_id() else self.get_agent_name(r["speaker"])
            preview = r["message"][:40]

            # 채널 라벨
            if ch_name.startswith("dm-"):
                label = f"{get_user_display_name()}과 DM"
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

    def _describe_channel(self, channel: str, my_agent_id: str) -> str:
        """채널 정보를 에이전트가 이해할 수 있는 형태로 설명"""
        participants = db.get_channel_participants(channel)

        # 참가자 이름 변환
        names = []
        for pid in participants:
            if pid == my_agent_id:
                continue  # 자기 자신은 제외
            profile = load_profile(pid)
            if profile:
                names.append(profile["name"])

        owner_name = get_user_display_name()

        # 채널 타입별 설명
        if channel.startswith("dm-"):
            return (
                f"[지금 대화 중: {owner_name}과(와) 1:1 대화. "
                f"이 대화에는 너와 {owner_name}만 있어. 다른 사람은 볼 수 없어.]"
            )
        elif channel.startswith("group-"):
            members = f"{owner_name}, " + ", ".join(names) if names else owner_name
            return (
                f"[지금 대화 중: {members}과(와) 단체 대화. "
                f"이 대화에는 여기 있는 사람들만 참여 중이야. "
                f"다른 사람을 초대하고 싶으면 유나한테 요청해.]"
            )
        elif channel.startswith("internal-dm-"):
            partner = names[0] if names else "?"
            return (
                f"[지금 대화 중: {partner}과(와) 둘만의 사적인 대화. "
                f"여기엔 너와 {partner}만 있어. 다른 사람은 아무도 못 봐.]"
            )
        elif channel.startswith("internal-group-"):
            members = ", ".join(names) if names else "?"
            return (
                f"[지금 대화 중: {members}과(와) 단체 대화. "
                f"여기엔 지금 있는 멤버만 참여 중이야. 다른 사람은 아무도 못 봐. "
                f"다른 사람을 초대하고 싶으면 유나한테 요청해.]"
            )
        elif channel == "mgr-dashboard":
            return (
                f"[지금 대화 중: {owner_name}과(와) 관리 채널. "
                f"여기엔 너와 {owner_name}만 있어.]"
            )
        elif channel == "mgr-creator":
            return (
                f"[지금 대화 중: {owner_name}과(와) 에이전트 생성 채널. "
                f"여기엔 너와 {owner_name}만 있어.]"
            )
        elif channel == "mgr-system-log":
            return "[시스템 로그 채널]"

        return ""

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
                    speaker = get_user_display_name() if r["speaker"] == get_user_id() else self.get_agent_name(r["speaker"])
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
        # raw window는 모든 에이전트 RAW_WINDOW(15)로 통일 — 컨텍스트 폭증 대신
        # memory.py L1/L2 요약이 그 이전 메시지의 사실을 보존 (구체적 명사/옵션/결정)
        _limit = RAW_WINDOW
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
            context = self._build_context(agent_info, channel, recent, user_message=user_message)
            full_prompt = context + "(자연스럽게 먼저 말 걸어)"

            model = _resolve_agent_model(agent_id, profile.get("type", "persona"))

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
        # raw window는 모든 에이전트 RAW_WINDOW(15)로 통일 — 컨텍스트 폭증 대신
        # memory.py L1/L2 요약이 그 이전 메시지의 사실을 보존 (구체적 명사/옵션/결정)
        _limit = RAW_WINDOW
        recent = db.get_recent_messages(channel, limit=_limit)

        log_writer.mark_thinking(agent_id)
        log_writer.agent_thinking(agent_id, f"응답 생성 시작 [{channel}]")

        # 단계별 타이밍 로그 + 하드 타임아웃 watchdog (>120초면 외부에서 stuck 알림)
        import time as _time, threading as _threading
        _t0 = _time.monotonic()
        _watchdog_fired = {"v": False}
        def _watchdog():
            if _watchdog_fired["v"]:
                return
            log_writer.system(f"⚠ {agent_id} 응답 생성 120초 초과 — stuck 가능성")
        _wd_timer = _threading.Timer(120.0, _watchdog)
        _wd_timer.daemon = True
        _wd_timer.start()

        try:
            if CLAUDE_AVAILABLE:
                responses = self._call_claude_code(agent_info, channel, recent, user_message)
            else:
                responses = self._placeholder_response(profile, user_message)
            elapsed = _time.monotonic() - _t0
            if elapsed > 60:
                log_writer.system(f"⚠ {agent_id} 응답 생성 {elapsed:.1f}초 (느림)")
        except Exception as e:
            import traceback
            log_writer.system(f"❌ generate_response 예외 ({agent_id}): {type(e).__name__}: {e}")
            log_writer.system(f"   trace: {traceback.format_exc()[:500]}")
            responses = self._placeholder_response(profile, user_message)
        finally:
            _watchdog_fired["v"] = True
            _wd_timer.cancel()
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

        # model override 체크 + 모델 전환 시 맥락 핸드오프
        if hasattr(self, '_model_override') and self._model_override:
            base_model = model
            model = self._model_override
            self._model_override = ""

            if base_model != model:
                # 모델 전환 — 이전 대화 요약 주입
                handoff = self._build_handoff_summary(agent_id, channel)
                if handoff:
                    full_prompt = handoff + "\n\n" + full_prompt
                log_writer.agent_thinking(agent_id, f"모델 전환: {base_model} → {model}")

        log_writer.agent_thinking(agent_id, f"Claude CLI 호출 ({model})")

        cli_args = [
            "claude",
            "-p", full_prompt,
            "--system-prompt", system_prompt,
            "--output-format", "text",
            "--model", model,
        ]
        cli_env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"}

        last_err = None
        for attempt in range(2):
            try:
                result = subprocess.run(
                    cli_args,
                    capture_output=True, text=True, timeout=60,
                    env=cli_env,
                )

                if result.returncode != 0:
                    err_detail = result.stderr[:200] if result.stderr else result.stdout[:200]
                    last_err = f"exit={result.returncode}: {err_detail}"
                    if attempt == 0:
                        log_writer.system(f"⚠ CLI 오류 ({last_err}) — 재시도")
                        import time; time.sleep(2)
                        continue
                    log_writer.system(f"❌ CLI 오류 ({last_err})")
                    return self._placeholder_response(profile, user_message)

                raw = result.stdout.strip()
                if not raw:
                    return ["..."]

                # Claude CLI 에러 메시지 감지 — 응답 전체가 에러면 placeholder
                if _looks_like_claude_error(raw):
                    _report_claude_error(name, raw, source="batch")
                    return self._placeholder_response(profile, user_message)

                # <tools> 블록 먼저 파싱 → calls는 stash, chat만 메시지 분리
                parsed = parse_tools_in_output(raw)
                self._last_tool_calls[agent_id] = parsed.tool_calls
                if parsed.errors:
                    log_writer.system(f"[Tools] 파싱 에러 ({name}): {'; '.join(parsed.errors[:3])}")
                return self._parse_response(parsed.chat, agent_name=name)

            except subprocess.TimeoutExpired:
                log_writer.system(f"❌ CLI 타임아웃 (60초)")
                return [f"({name} 응답 지연 — 다시 시도해주세요)"]
            except FileNotFoundError:
                print("[Runtime] claude CLI를 찾을 수 없습니다")
                return self._placeholder_response(profile, user_message)
            except Exception as e:
                log_writer.system(f"❌ 런타임 오류: {e}")
                return self._placeholder_response(profile, user_message)

        log_writer.system(f"❌ CLI 재시도 실패: {last_err}")
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
        # raw window는 모든 에이전트 RAW_WINDOW(15)로 통일 — 컨텍스트 폭증 대신
        # memory.py L1/L2 요약이 그 이전 메시지의 사실을 보존 (구체적 명사/옵션/결정)
        _limit = RAW_WINDOW
        recent = db.get_recent_messages(channel, limit=_limit)

        # 오너 메시지 먼저 로깅
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

        # _build_prompt 단계 timing — stuck 위치 식별용
        import time as _time
        _bp_start = _time.monotonic()
        try:
            full_prompt, system_prompt, model = self._build_prompt(
                agent_info, channel, recent, user_message
            )
        except Exception as e:
            import traceback
            log_writer.mark_done(agent_id)
            log_writer.system(f"❌ _build_prompt 예외 ({agent_id}): {type(e).__name__}: {e}")
            log_writer.system(f"   trace: {traceback.format_exc()[:400]}")
            on_message(f"({name} 응답 생성 실패)")
            return [f"({name} 응답 생성 실패)"]
        _bp_elapsed = _time.monotonic() - _bp_start
        if _bp_elapsed > 5:
            log_writer.system(f"⏱ {agent_id} _build_prompt {_bp_elapsed:.1f}s")

        log_writer.agent_thinking(agent_id, f"Claude CLI 호출 ({model})")

        messages = []
        seen = set()
        tool_buffer: list[str] = []  # <tools> 블록 누적 (chat 스트림에서 제외)
        in_tools = False

        # 에이전트 타입별 최대 응답 수 제한
        MAX_STREAMING_MESSAGES = {
            "persona": 10,
            "mgr": 15,
            "creator": 10,
        }
        agent_type = profile.get("type", "persona")
        max_messages = MAX_STREAMING_MESSAGES.get(agent_type, 10)

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

            # Hard watchdog — Claude CLI가 stdout 안 닫고 hang 시 강제 kill (120s)
            import threading as _threading
            _wd_killed = {"v": False}
            _intentional_kill = False  # max_messages 초과로 의도적 kill 추적
            def _wd_kill():
                if process.poll() is None:
                    _wd_killed["v"] = True
                    log_writer.system(f"❌ {name} CLI 응답 120초 초과 — 강제 kill")
                    try:
                        process.kill()
                    except Exception:
                        pass
            _wd = _threading.Timer(120.0, _wd_kill)
            _wd.daemon = True
            _wd.start()

            for line in process.stdout:
                raw_line = line.rstrip("\n")
                line = raw_line.strip()
                if not line:
                    if in_tools:
                        tool_buffer.append("")
                    continue

                # <tools> 블록 진입 감지 — 이 시점 이후는 chat으로 방출 금지
                if "<tools>" in line.lower() and not in_tools:
                    in_tools = True
                    tool_buffer.append(raw_line)
                    continue
                if in_tools:
                    tool_buffer.append(raw_line)
                    if "</tools>" in line.lower():
                        # 블록 끝 — 이후 line이 또 있을 경우 무시 또는 체크
                        pass
                    continue

                # [MSG] 태그 처리
                line = line.replace("[MSG]", "")
                import re as _re
                # 프롬프트 example placeholder ({name}, {topic}, {field} 등)가 그대로
                # 채팅에 새는 거 차단. 영어 lowercase 식별자만 한정해서 한국어/이모지는 안 건드림.
                line = _re.sub(r'\{[a-z_][a-z0-9_]*\}', '', line)
                cleaned = " ".join(line.split())
                if not cleaned:
                    continue

                # Claude CLI 에러 메시지 누출 차단 (사용량 한도, API 에러 등)
                if _looks_like_claude_error(cleaned):
                    _report_claude_error(name, cleaned, source="stream")
                    # 에러 감지 시 즉시 스트리밍 종료 — 추가 에러 텍스트 방출 방지
                    try:
                        process.kill()
                    except Exception:
                        pass
                    break

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

                # 최대 응답 수 초과 시 중단
                if len(messages) >= max_messages:
                    log_writer.system(f"⚠ {name} 응답 {max_messages}건 도달 — 스트리밍 종료")
                    process.kill()
                    _intentional_kill = True
                    break

            try:
                _wd.cancel()
            except Exception:
                pass
            process.wait(timeout=60)
            if _wd_killed["v"] and not messages:
                msg = f"({name} 응답 지연 — 다시 시도해주세요)"
                on_message(msg)
                messages = [msg]

            # <tools> 블록 파싱 → stash
            if tool_buffer:
                try:
                    parsed = parse_tools_in_output("\n".join(tool_buffer))
                    self._last_tool_calls[agent_id] = parsed.tool_calls
                    if parsed.errors:
                        log_writer.system(f"[Tools] 파싱 에러 ({name}): {'; '.join(parsed.errors[:3])}")
                except Exception as e:
                    log_writer.system(f"[Tools] 스트림 파싱 실패: {e}")

            if process.returncode != 0 and not _intentional_kill:
                stderr = process.stderr.read() if process.stderr else ""
                err_detail = stderr[:200] if stderr.strip() else "(stderr empty)"
                log_writer.system(f"❌ CLI 오류 (exit={process.returncode}): {err_detail}")
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
            try:
                _wd.cancel()
            except Exception:
                pass
            log_writer.mark_done(agent_id)
            log_writer.agent_thinking(agent_id, f"응답 완료 {len(messages)}건")

        # DB 로깅은 handlers에서 디스코드 전송 후 처리
        # (대시보드에 디스코드보다 먼저 보이는 문제 방지)

        return messages

    # ── Response parsing ─────────────────────────────

    def _parse_response(self, raw: str, agent_name: str = "") -> list[str]:
        if not raw:
            return ["..."]

        raw = raw.replace("[MSG]", "\n")
        lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        if not lines:
            return ["..."]

        # CMD/QUERY/ACTION 태그가 포함된 줄은 태그만 보존 (대화 내용과 분리)
        _tag_pattern = re.compile(r'\[(?:CMD|QUERY|ACTION):((?:[^\[\]]|\[[^\]]*\])*)\]')

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
            if not cleaned:
                continue
            # Claude CLI 에러 메시지 누출 차단
            if _looks_like_claude_error(cleaned):
                _report_claude_error(agent_name, cleaned, source="parse")
                continue
            # JSON/구조화 데이터 유출 필터
            if (cleaned.startswith("{") or cleaned.startswith('"') or
                    '":"' in cleaned or 'target_id' in cleaned or
                    'relationship_templates' in cleaned or
                    'is_owner_relationship' in cleaned):
                continue
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
        owner_call = rel.get("pet_name") or get_user_display_name() or "사용자"

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
        base_context = self._build_context(speaker_info, channel, recent, user_message=context)

        # 엄격한 role guard — 하나가 유나 역할까지 같이 생성하는 버그 방지.
        # 같은 내용 재요약 방지 — internal-dm 에서 같은 보고를 4-5회 반복하는 회귀 발견.
        role_guard = (
            f"\n[역할 엄수] 너는 {speaker_name} 한 사람. "
            f"{listener_name} 의 대사/답변은 절대 쓰지 마. 내가 한 턴 말하면 끝, "
            f"상대 반응은 상대가 알아서 함.\n"
            f"[출력] 한 번에 카톡 1~4개 짧은 메시지만. 긴 독백·양쪽 대화 시뮬레이션 금지.\n"
            f"[반복 금지] 네가 이미 한 말은 절대 재요약·재진술 하지 마. 위 대화이력에 "
            f"본인의 같은 요지 메시지가 이미 있으면 그 주제는 종료됐다는 뜻. 다음 화제 or 마무리로 넘어가.\n"
            f"[종료 감지] 대화가 맴돌면 '그럼 이따 봐' '또 얘기하자' 같이 자연스럽게 끊어. "
            f"끝없이 맴돌지 마."
        )
        if context:
            full_prompt = base_context + f"상황: {context}\n{listener_name}과(와)의 대화를 이어가.{role_guard}"
        else:
            full_prompt = base_context + f"{listener_name}과(와)의 대화를 이어가.{role_guard}"

        speaker_type = speaker_info["profile"].get("type", "persona")
        model = _resolve_agent_model(speaker_id, speaker_type)

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
                        # <tools> 블록 먼저 파싱 → tool_calls stash, chat 텍스트만 분리
                        # (이전에는 이 경로에서 <tools> 파싱이 빠져서 internal-dm에서
                        # 유나가 finish_onboarding 호출해도 원문이 채팅으로 새고 실행 안 됨)
                        parsed = parse_tools_in_output(result.stdout.strip())
                        self._last_tool_calls[speaker_id] = parsed.tool_calls
                        if parsed.errors:
                            log_writer.system(
                                f"[Tools] 파싱 에러 (A2A {speaker_name}): {'; '.join(parsed.errors[:3])}"
                            )
                        responses = self._parse_response(parsed.chat, agent_name=speaker_name)
                        # 역할 leak 방어 — listener 이름으로 시작하거나 "답장 시뮬레이션" 패턴 차단
                        import re as _role_re
                        _leak_patterns = [
                            rf"^\s*{_role_re.escape(listener_name)}\s*[:：]",  # "유나: ..." 형태
                            rf"^\s*\[?\s*{_role_re.escape(listener_name)}\s*\]?",  # "[유나] ..."
                        ]
                        cleaned = []
                        dropped = 0
                        for msg in responses:
                            leaked = any(_role_re.match(p, msg) for p in _leak_patterns)
                            if leaked:
                                dropped += 1
                                continue
                            cleaned.append(msg)
                        if dropped:
                            log_writer.system(
                                f"[A2A] {speaker_name} 응답에서 {listener_name} 역할 leak {dropped}건 제거"
                            )
                        responses = cleaned
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

            # LLM 호출 실패 — 이전엔 [테스트] 플레이스홀더를 채팅으로 노출시켰으나
            # 유저 경험 저해. 빈 list 반환 → 호출부에서 "전송할 내용 없음" 처리.
            log_writer.system(
                f"⚠ A2A 응답 생성 실패 (CLAUDE_AVAILABLE={CLAUDE_AVAILABLE}) — "
                f"{speaker_name}→{listener_name}"
            )
            return []
        finally:
            log_writer.mark_done(speaker_id)


# 싱글턴
runtime = AgentRuntime()
