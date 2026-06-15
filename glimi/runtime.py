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
from .memory import check_and_summarize, get_memory_context, RAW_WINDOW
from .tools import parse_response as parse_tools_in_output, ToolCall
from .tools import strip_control_tokens as _strip_control_tokens

# ── 커널 의존성 주입 (Phase 2) — 런타임은 DB/프로필/관측을 직접 안 보고 추상 인터페이스로만 접근.
# KernelStore(데이터) · ProfileProvider(페르소나) · OwnerContext(오너) · KernelObserver(관측/로그).
# 커널은 앱 어댑터를 import 하지 않는다 (standalone 설치 가능). 앱이 set_store()/
# set_profiles()/set_owner()/set_observer() 로 주입 (src/core/runtime.py shim 참조).
from .observability import NullObserver

_store = None
_profiles = None
_owner = None
_observer = NullObserver()

# 선택적 앱 훅 (미등록 = no-op, standalone 동작) — 앱-특화 기능을 커널 밖으로.
_leak_reporter = None        # fn(agent_id, channel, leaked_text, source) — self-healing dev-request 등
_profile_reminder_fn = None  # fn(owner_profile: dict) -> Optional[str] — 오너 프로필 이상치 힌트


def set_store(store):
    """KernelStore 구현 주입 (미호출 시 기본 SQLite 어댑터)."""
    global _store
    _store = store


def set_profiles(provider):
    """ProfileProvider 구현 주입 (미호출 시 기본 profile 어댑터)."""
    global _profiles
    _profiles = provider


def set_owner(owner):
    """OwnerContext 구현 주입 (미호출 시 기본 profile 어댑터)."""
    global _owner
    _owner = owner


def set_observer(obs):
    """KernelObserver 구현 주입 (미호출 시 기본 log_writer 어댑터)."""
    global _observer
    _observer = obs


def set_leak_reporter(fn):
    """leak 자동 보고 훅 등록. fn(agent_id, channel, leaked_text, source). 미등록=no-op."""
    global _leak_reporter
    _leak_reporter = fn


def set_profile_reminder_fn(fn):
    """오너 프로필 이상치 힌트 훅 등록. fn(owner_profile: dict) -> Optional[str]. 미등록=no-op."""
    global _profile_reminder_fn
    _profile_reminder_fn = fn


def _check_claude_cli() -> bool:
    return shutil.which("claude") is not None


CLAUDE_AVAILABLE = _check_claude_cli()

# Claude CLI subprocess 는 반드시 Glimi 프로젝트 밖에서 실행. 프로젝트 루트 cwd 로 돌면
# CLAUDE.md 가 로드돼 Claude Code 가 "코딩 작업" 컨텍스트 상속하면서 에이전트가 개인
# 대화 내용에 대해 clarifying-refusal 을 뱉거나 meta-commentary 를 주입. HOME 은 프로젝트
# CLAUDE.md 없으니 안전. (src.llm.ClaudeCLIBackend 도 동일 원칙 적용.)
_CLI_CWD = os.path.expanduser("~")

AGENT_MODELS = {
    "persona": "claude-haiku-4-5",   # 대화량 많고 지연 민감 — 기본 Haiku, 필요시 대시보드에서 per-agent Sonnet override
    "mgr": "claude-sonnet-4-6",
    "creator": "claude-sonnet-4-6",  # 대화는 소넷
    "dev": "claude-sonnet-4-6",      # triage / chat 응답은 Sonnet — 코드 수정은 별도 dev_dispatch_fix subprocess 가 Opus
}
AGENT_TASK_MODELS = {
    "creator": "claude-opus-4-8",  # 프로필 JSON 생성은 opus
    "dev": "claude-opus-4-8",      # 실제 코드 수정 subprocess (dev_dispatch_fix) — 최신 Opus
}

# 대시보드에서 선택 가능한 모델 카탈로그.
# Phase 1: 클라우드(Claude) 모델만. Phase 2 에서 로컬 모델 (ollama/vllm 등) 여러 종 추가.
# kind: "cloud" | "local" — UI 에서 ☁️/🖥️ 아이콘으로 구분.
# provider: "claude" | "ollama" | "vllm" | "llamacpp" — 백엔드 선택에도 사용.
AVAILABLE_MODELS = [
    {"id": "claude-opus-4-8", "label": "Opus 4.8",
     "kind": "cloud", "provider": "claude", "tier": "powerful", "icon": "☁️"},
    {"id": "claude-sonnet-4-6", "label": "Sonnet 4.6",
     "kind": "cloud", "provider": "claude", "tier": "balanced", "icon": "☁️"},
    {"id": "claude-haiku-4-5", "label": "Haiku 4.5",
     "kind": "cloud", "provider": "claude", "tier": "fast", "icon": "☁️"},
    # 로컬 (Ollama) — id 의 "ollama:" prefix 가 백엔드 라우팅 마커.
    # "ollama:local" = GLIMI_OLLAMA_MODEL env 따름. 구체 태그는 그 모델 강제 (per-agent).
    {"id": "ollama:local", "label": "로컬 (전역 설정)",
     "kind": "local", "provider": "ollama", "tier": "balanced", "icon": "🖥️"},
    {"id": "ollama:gemma4-26b-a4b-abl:iq3", "label": "Gemma4 26B-A4B (local)",
     "kind": "local", "provider": "ollama", "tier": "quality", "icon": "🖥️"},
    {"id": "ollama:huihui_ai/gemma-4-abliterated:e4b", "label": "Gemma4 E4B (local)",
     "kind": "local", "provider": "ollama", "tier": "balanced", "icon": "🖥️"},
    {"id": "ollama:huihui_ai/gemma-4-abliterated:e2b", "label": "Gemma4 E2B (local)",
     "kind": "local", "provider": "ollama", "tier": "fast", "icon": "🖥️"},
    # 향후: vllm / llamacpp provider.
]


def _resolve_agent_model(agent_id: str, agent_type: str) -> str:
    """실효 모델 결정 — DB override 우선, 없으면 AGENT_MODELS[type] 기본값.
    매 호출마다 조회 → 대시보드에서 변경 시 즉시 반영 (재시작 불필요).
    컨텍스트 연속성: 대화 이력·메모리는 DB 기반이라 모델 바뀌어도 그대로 이어감."""
    try:
        override = _store.get_agent_model_override(agent_id)
        if override:
            return override
    except Exception:
        pass
    return AGENT_MODELS.get(agent_type, "claude-sonnet-4-6")
OPUS_MODEL = "claude-opus-4-8"


def _provider_for(agent_type: str, model: str) -> str:
    """이 호출이 어느 백엔드로 갈지 결정 — 'claude' (직접 CLI) | 'ollama' (src.llm).

    우선순위 (src/llm/__init__._select_backend 와 일관):
      1) GLIMI_LLM_AGENT_MAP (agent_type 별 매핑) — 하이브리드 탈출구
         예: {"persona":"ollama","mgr":"claude_cli"}
      2) GLIMI_LLM_BACKEND (전역 강제)
      3) model id prefix ("ollama:...")
      4) AVAILABLE_MODELS 레지스트리의 provider
    """
    # 1) agent_type 별 매핑
    raw = os.environ.get("GLIMI_LLM_AGENT_MAP", "").strip()
    if raw:
        try:
            m = json.loads(raw)
            if isinstance(m, dict):
                v = (m.get(agent_type) or m.get("_default") or "").strip().lower()
                if v:
                    return "ollama" if v == "ollama" else "claude"
        except Exception:
            pass
    # 2) 전역 백엔드
    glob = os.environ.get("GLIMI_LLM_BACKEND", "").strip().lower()
    if glob == "ollama":
        return "ollama"
    if glob in ("claude_cli", "anthropic_sdk", "claude"):
        return "claude"
    # 3) model id prefix
    if model.startswith("ollama:"):
        return "ollama"
    # 4) 레지스트리
    for mm in AVAILABLE_MODELS:
        if mm["id"] == model:
            return "ollama" if mm.get("provider") == "ollama" else "claude"
    return "claude"


def _ollama_model_map() -> dict:
    """GLIMI_OLLAMA_MODEL_MAP (JSON) — agent_type 별 ollama 모델 태그 매핑.
    예: {"mgr": "gemma4:26b-a4b-it-q4_K_M", "persona": "gemma4:e4b-it-q4_K_M"}
    "_default" 키는 미지정 타입의 폴백."""
    raw = os.environ.get("GLIMI_OLLAMA_MODEL_MAP", "").strip()
    if not raw:
        return {}
    try:
        m = json.loads(raw)
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _ollama_model_arg(model: str, agent_type: str = "") -> str:
    """ollama 백엔드에 넘길 모델 태그 결정. 우선순위:
      1) 에이전트 개별 — model 이 "ollama:<tag>" (DB agents.model_override 경유)
      2) 타입별 — GLIMI_OLLAMA_MODEL_MAP[agent_type] (없으면 "_default")
      3) 전역 — GLIMI_OLLAMA_MODEL (src/llm/ollama.py _resolve_model 폴백)
    구체 태그를 반환하면 ollama.py 가 그대로 사용, "local"/claude id 면 전역 env 적용.
    """
    if model.startswith("ollama:"):
        tag = model.split(":", 1)[1]
        if tag and tag != "local":
            return tag
        model = "local"
    mm = _ollama_model_map()
    v = (mm.get(agent_type) or mm.get("_default") or "").strip() if mm else ""
    if v:
        return v
    return model or "local"


def _ollama_display_model(model: str, agent_type: str = "") -> str:
    """로그 표시용 — 실제 ollama 가 쓸 모델명."""
    resolved = _ollama_model_arg(model, agent_type)
    if resolved and resolved != "local" and not resolved.startswith("claude"):
        return resolved
    return os.environ.get("GLIMI_OLLAMA_MODEL", "").strip() or resolved


# ollama 가용성은 True 면 캐시 (세션 중 안 죽는다고 가정). False/미확인이면 매번 재확인 —
# 봇 기동 후 ollama 가 늦게 떠도 다음 호출에서 잡히도록.
_OLLAMA_OK = {"v": False}


def _backend_available(provider: str) -> bool:
    """해당 provider 백엔드가 호출 가능한지. False 면 placeholder 로 폴백."""
    if provider != "ollama":
        return CLAUDE_AVAILABLE
    if _OLLAMA_OK["v"]:
        return True
    try:
        from .llm.ollama import OllamaBackend
        ok = OllamaBackend().available()
    except Exception:
        ok = False
    _OLLAMA_OK["v"] = ok
    return ok


def _normalize(s):
    return re.sub(r'[.?!,~\s…·ㅋㅎㅠ]', '', s).lower()


# Internal-monologue / silence-reasoning leak 패턴. LLM 이 침묵 결정을 채팅에 그대로
# 출력하는 회귀 (`[침묵]`, `대화가 마무리됐으니까 응답 없음]`, `NO_REPLY (이유)` 등).
# persona.py / mgr.py / creator.py 시스템 프롬프트가 NO_REPLY 토큰을 가르쳐도, 모델이
# 가끔 이유를 덧붙이거나 reasoning 자체를 출력 → 후처리에서 한 번 더 차단.
_REASONING_PREFIX_RE = re.compile(
    # bare "침묵" 은 자연 발화 가능 ("침묵 깨고 ...") — 토픽 marker 붙은 reasoning 전용 형태만 잡음
    r"^\s*[\[\(]?\s*(?:빈\s*응답|응답\s*없음|침묵(?:이라|이\s|이가|만\s|이$)|silence is|NO[_\s-]?REPLY)",
    re.IGNORECASE,
)
# Bracket 만으로 둘러싼 짧은 메타 태그 — `[침묵]` `[silence]` `[no reply]` `[...]`
_BRACKET_META_RE = re.compile(
    r"^\s*[\[\(]\s*(?:침묵|silence|no\s*reply|응답\s*없음|\.{2,}|…+)\s*[\]\)]\s*$",
    re.IGNORECASE,
)
_REASONING_PAREN_RE = re.compile(
    r"^\s*[\[\(][^\[\(\]\)]*?(?:침묵이|마무리됐|루프|자연스러우?[움면니워]|응답\s*없|"
    r"silence is|conversation\s+(?:has\s+)?(?:ended|wrapped)|naturally\s+ended)",
    re.IGNORECASE,
)
# Reasoning sentence 가 닫는 `]`/`)` 만 달랑 붙은 채로 끝나는 경우
# 예: "대화가 충분히 예쁘게 마무리됐으니까 응답 없음]"
_REASONING_TAIL_BRACKET_RE = re.compile(
    r"(?:응답\s*없|침묵이|마무리됐|루프|자연스러우?[움면니워])[^\[\(\]\)]*[\]\)]\s*$",
    re.IGNORECASE,
)
# 단독 "..." 또는 "....." 라인 — persona 가 침묵 표현으로 점만 출력하는 회귀
_DOTS_ONLY_RE = re.compile(r"^[\s.…]+$")

# Markdown status report leak — assistant-style 구조화 응답 (관찰: 2026-05-04 서하은
# internal-dm-지수-서하은 채널에 "현재 상황을 정리하면:" + bullet list 그대로 흘림).
# 채팅엔 이런 메타 정리·계획 출력이 절대 들어가면 안 됨.
_STATUS_REPORT_PHRASE_RE = re.compile(
    r"(현재\s*상황을?\s*정리|상황\s*정리하면|이어나가겠습니다|이어가겠습니다|"
    r"진행\s*상황[은:]|다음\s*반응이\s*오면|natural(?:ly)?\s+continue\s+the\s+conversation|"
    r"summary\s+of\s+the\s+(?:current\s+)?(?:state|situation)|let me (?:summari[sz]e|continue))",
    re.IGNORECASE,
)
# bold-key bullet ("- **심재빈과의 DM**: 진행 중") — 자연 채팅엔 없는 형식.
_BOLD_BULLET_RE = re.compile(r"^\s*[-*]\s*\*\*[^*]+\*\*\s*:")


def _auto_report_leak(agent_id: str, channel_name: str, leaked_text: str, source: str):
    """leak 감지 시 앱이 등록한 reporter 로 통지 (self-healing dev-request 적재 등).
    앱 미등록(standalone)이면 no-op — 커널은 dev 큐/커뮤니티를 모름."""
    if _leak_reporter is None:
        return
    try:
        _leak_reporter(agent_id, channel_name, leaked_text, source)
    except Exception as e:
        _observer.system(f"[leak auto-report] 실패 (무시): {type(e).__name__}: {e}")


def _looks_like_owner_echo(line: str) -> bool:
    """라인이 '오너이름: ...' / '별칭: ...' 형태 = 유저 발화 에코 (로컬 모델이 대화 포맷을
    그대로 복사). 오너 이름/별칭으로 시작하면 drop. 짧은 이름만(오인 방지)."""
    try:
        names = set()
        n = _owner.display_name()
        if n:
            names.add(n)
        oc = _owner.call_name()
        if oc:
            names.add(oc)
    except Exception:
        return False
    for nm in names:
        if nm and 1 <= len(nm) <= 12 and (line.startswith(f"{nm}:") or line.startswith(f"{nm} :")):
            return True
    return False


def _is_reasoning_leak(text: str) -> bool:
    """채팅에 새어나간 LLM 의 침묵·결정·내레이션을 감지. True 면 메시지 drop."""
    if not text:
        return False
    s = text.strip()
    if not s:
        return False
    if _REASONING_PREFIX_RE.match(s):
        return True
    if _BRACKET_META_RE.match(s):
        return True
    if _REASONING_PAREN_RE.match(s):
        return True
    if _REASONING_TAIL_BRACKET_RE.search(s):
        return True
    if _STATUS_REPORT_PHRASE_RE.search(s):
        return True
    if _BOLD_BULLET_RE.match(s):
        return True
    # "..." 단독 — 빈 메시지 placeholder 인 경우 _parse_response 가 별도 처리하므로
    # 여기서는 진짜 점만 있는 짧은 라인만 잡음
    if len(s) <= 6 and _DOTS_ONLY_RE.match(s):
        return True
    return False


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
    # 메타 단어 누출 방어 — LLM 이 실수로 "Claude Code" 뱉으면 감지해서 drop
    "claude code",
    "claude-code",
    "connection error",
    "연결이 끊",
    "연결 끊겨",
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
    """LLM 에러 텍스트 필터링 시 observer 로 system 로그 남김.
    (플랫폼별 추가 송출 — Discord mgr-system-log 등 — 은 앱의 KernelObserver 구현 책임.)"""
    snippet = text.strip().replace("\n", " ")[:200]
    msg = f"⚠ LLM 에러 필터 [{agent_name}/{source}]: {snippet}"
    _observer.system(msg)


class AgentRuntime:

    def __init__(self):
        self._active_agents: dict[str, dict] = {}
        # 최근 응답에서 추출한 tool_calls 저장소 (key=agent_id, consume 후 삭제)
        self._last_tool_calls: dict[str, list[ToolCall]] = {}
        # 다음 호출 시 prompt에 주입할 <tool_results> 블록 (key=agent_id:channel)
        self._pending_tool_results: dict[str, str] = {}

        _glob = os.environ.get("GLIMI_LLM_BACKEND", "").strip().lower()
        if _glob == "ollama":
            _m = os.environ.get("GLIMI_OLLAMA_MODEL", "?")
            _mm = _ollama_model_map()
            _map_note = f", type_map={_mm}" if _mm else ""
            print(f"[Runtime] LLM 백엔드: Ollama (model={_m}{_map_note}) — 로컬 대화 모드")
        elif CLAUDE_AVAILABLE:
            print("[Runtime] Claude Code CLI 감지됨 — 실제 대화 모드")
        else:
            print("[Runtime] Claude Code CLI 미감지 — placeholder 모드")
            print("[Runtime]   설치: npm install -g @anthropic-ai/claude-code")

    def activate_agent(self, agent_id: str) -> bool:
        profile = _profiles.get(agent_id)
        if not profile:
            return False

        # 모델 인지 prompt dialect (tool_call_syntax_hint 등) 를 위해 model 을 provider 에 넘김.
        # active-model 스코핑은 ProfileProvider 구현(앱) 책임 — 커널은 prompts 레이어를 모름.
        model_id = _resolve_agent_model(agent_id, profile.get("type", "persona"))
        system_prompt = _profiles.system_prompt(agent_id, model=model_id)

        self._active_agents[agent_id] = {
            "profile": profile,
            "system_prompt": system_prompt,
        }
        print(f"[Runtime] {profile['name']} ({agent_id}) 활성화")
        return True

    def get_active_agents(self) -> list[str]:
        return list(self._active_agents.keys())

    def get_agent_name(self, agent_id: str) -> str:
        return _profiles.display_name(agent_id)

    # ── Prompt building ──────────────────────────────

    def _build_context(self, agent_info: dict, channel: str, recent: list[dict],
                       user_message: str = "", mem_scale: float = 1.0) -> str:
        """에이전트 맥락 구성 (채널 정보 + 감정 + 메모리 + 대화이력).

        mem_scale: 메모리 주입 예산 배수 (context_budget.plan 이 num_ctx 기준 산출)."""
        import time as _time
        _t = _time.monotonic()
        def _checkpoint(label):
            nonlocal _t
            now = _time.monotonic()
            dt = now - _t
            if dt > 5.0:
                _observer.system(f"⏱ _build_context[{label}] {dt:.1f}s")
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
        agent_state = _store.get_agent(agent_id)
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

            # 오너 프로필 이상치 힌트 — 앱이 등록한 훅 사용 (미등록=skip). 커널은 검사 로직 모름.
            if _profile_reminder_fn is not None:
                try:
                    hint = _profile_reminder_fn(_owner.profile() or {})
                    if hint:
                        reminder_parts.append(hint)
                except Exception as e:
                    print(f"[runtime] 프로필 이상치 훅 실패 (무시): {e}")
            _checkpoint("profile_anomalies")

        # ── 기억 섹션 (5 레이어 통합) ──
        # user_message + 최근 대화 텍스트를 entity 매칭용 힌트로 넘김
        focus_hint = user_message + "\n" + "\n".join(m.get("message", "") for m in recent[-5:])
        memory_text = get_memory_context(agent_id, channel, user_message=focus_hint, scale=mem_scale)
        _checkpoint("memory_context")

        if memory_text:
            reminder_parts.append("━━━ 기억 ━━━\n" + memory_text + "\n━━━━━━━━━━━")

        # ── 다른 채널 최근 대화 (요약 없이 직접 주입) ──
        # 첫 발화 (이 채널 기존 메시지 2 미만) 시 cross-channel peek 주입 X.
        # Haiku 가 다른 채널 주제를 현재 대화로 끌고 오는 bleed 방지 (QA 회귀: 지아가 internal-dm-지아-소연
        # 시작 발화에서 dm-지아 의 "개발자" 주제 그대로 꺼냄).
        # 매니저/크리에이터는 채널 간 브릿지가 본질이라 더 풍성하게 + "활용 가능" 라벨로 주입.
        if len(recent) >= 2:
            cross_recent = self._get_cross_channel_recent(agent_id, channel, agent_type=agent_type)
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
                    if msg["speaker"] == _owner.id():
                        filtered.append(msg)
                    elif len(filtered) == 0 or filtered[-1]["speaker"] == _owner.id():
                        # 오너 메시지 바로 다음 유나 응답만 포함
                        filtered.append(msg)
                for msg in filtered[-15:]:
                    speaker = _owner.display_name() if msg["speaker"] == _owner.id() else self.get_agent_name(msg["speaker"])
                    prompt_parts.append(f"{speaker}: {msg['message']}")
            else:
                for msg in recent:
                    speaker = _owner.display_name() if msg["speaker"] == _owner.id() else self.get_agent_name(msg["speaker"])
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
        atype = agent_info["profile"].get("type", "persona")
        system_prompt = agent_info["system_prompt"]
        model = _resolve_agent_model(agent_id, atype)

        # 이전 턴의 tool_results가 있으면 user_message 앞에 주입
        tool_results = self._consume_tool_results(agent_id, channel)
        name = speaker_name or _owner.display_name()

        # 최근 자기 도구 호출 이력 주입 — mgr/creator 만.
        # raw conversation 엔 도구 호출 이력이 안 들어가서, 유나가 직전에
        # request_dm 호출한 걸 다음 턴에 기억 못 함 → 같은 요청 무한 반복 (QA 관찰 버그).
        tool_history = ""
        if atype in ("mgr", "creator"):
            tool_history = self._build_recent_tool_history(agent_id)

        # ── 컨텍스트 예산 (ollama 등 작은 컨텍스트만) ──────────
        # num_ctx 에 맞춰 메모리 풍부도(scale) 결정 + 최근 대화 trim → 절대 초과 안 함.
        # Claude 등 대용량 컨텍스트는 scale=1.0 / trim 없음 (기존 동작 보존).
        mem_scale = 1.0
        if _provider_for(atype, model) == "ollama":
            try:
                from . import context_budget as _cb
                _num_ctx = _cb.resolve_num_ctx()
                _fixed_extra = (tool_history or "") + (tool_results or "")
                _plan = _cb.plan(_num_ctx, atype, system_prompt, user_message, _fixed_extra)
                mem_scale = _plan["mem_scale"]
                _before = len(recent)
                recent = _cb.trim_recent_to_budget(recent, _plan["recent_token_budget"])
                # 시스템 프롬프트만으로 예산 초과 — 메모리/대화 0 으로도 못 막음.
                # (mgr 캐릭터+도구 ≈5000tok 라 num_ctx 8192 미만이면 발생.) 관찰 가능하게 경고.
                if _plan["system_tokens"] >= _plan["prompt_budget"]:
                    _observer.system(
                        f"⚠ [ctx-budget] {agent_id} 시스템 프롬프트({_plan['system_tokens']}tok)가 "
                        f"예산({_plan['prompt_budget']}tok) 초과 — num_ctx={_num_ctx} 너무 작음. "
                        f"{atype} 는 8192+ 권장 (GLIMI_OLLAMA_NUM_CTX)"
                    )
                elif len(recent) < _before or mem_scale < 0.999:
                    _observer.system(
                        f"[ctx-budget] {agent_id} num_ctx={_num_ctx} mem_scale={mem_scale} "
                        f"recent {_before}→{len(recent)} (budget {_plan['recent_token_budget']}tok)"
                    )
            except Exception as _e:
                _observer.system(f"[ctx-budget] 예산 계산 실패 (무시): {type(_e).__name__}: {_e}")

        context = self._build_context(agent_info, channel, recent,
                                      user_message=user_message, mem_scale=mem_scale)

        pieces = [context]
        if tool_history:
            pieces.append(tool_history)
        if tool_results:
            pieces.append(tool_results)
        pieces.append(f"{name}: {user_message}")
        full_prompt = "\n".join(pieces) if len(pieces) > 1 else pieces[0]

        return full_prompt, system_prompt, model

    def _build_recent_tool_history(self, agent_id: str, window_sec: int = 300) -> str:
        """최근 window_sec 초 내 이 에이전트가 호출한 주요 도구 이력.
        events 테이블에서 dm_request 등 조회 → prompt 주입용 텍스트."""
        try:
            # participants 의 첫 토큰이 caller — agent_id 매칭 (store 가 LIKE 구성)
            rows = _store.get_recent_events(agent_id, ["dm_request"], window_sec, limit=8)
        except Exception:
            return ""
        if not rows:
            return ""
        lines = ["[최근 네가 호출한 도구 이력 — 같은 요청 반복 금지]"]
        import datetime as _dt
        now = _dt.datetime.utcnow()
        for r in rows:
            try:
                ts = _dt.datetime.fromisoformat(r["timestamp"].replace(" ", "T"))
                mins = int((now - ts).total_seconds() // 60)
                elapsed = f"{mins}분 전" if mins >= 1 else "방금 전"
            except Exception:
                elapsed = "최근"
            parts = (r["participants"] or "").split(",")
            target = parts[1] if len(parts) > 1 else "?"
            desc = (r["description"] or "")[:100]
            lines.append(f"- [{elapsed}] {r['event_type']} → {target}: {desc}")
        lines.append("→ 위 이력의 요청은 이미 전달됨. 응답 기다리는 중. 같은 target 에 비슷한 내용 또 보내면 스팸.")
        return "\n".join(lines) + "\n"

    def _build_handoff_summary(self, agent_id: str, channel: str) -> str:
        """모델 전환 시 이전 대화 맥락 요약 생성 (haiku로 빠르게)"""
        recent = _store.get_recent_messages(channel, limit=15)
        if not recent:
            return ""

        lines = []
        for r in recent:
            speaker = _owner.display_name() if r["speaker"] == _owner.id() else self.get_agent_name(r["speaker"])
            lines.append(f"{speaker}: {r['message']}")
        conversation = "\n".join(lines[-10:])

        summary_prompt = (
            f"아래 대화를 3~4문장으로 요약해. 누가 뭘 요청했고 어디까지 진행됐는지 핵심만:\n\n{conversation}"
        )
        provider = _provider_for("persona", "claude-haiku-4-5")
        try:
            if provider == "ollama":
                from . import llm
                _r = llm.generate(
                    system="", user=summary_prompt,
                    model=_ollama_model_arg("ollama:local", "persona"), agent_type="persona",
                    max_tokens=512, timeout=60,
                )
                if not _r.error and (_r.text or "").strip():
                    return f"[이전 대화 요약] {_r.text.strip()}"
            else:
                result = subprocess.run(
                    ["claude", "-p", summary_prompt,
                     "--output-format", "text", "--model", "claude-haiku-4-5"],
                    capture_output=True, text=True, timeout=15,
                    env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
                    cwd=_CLI_CWD,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return f"[이전 대화 요약] {result.stdout.strip()}"
        except Exception:
            pass

        # 요약 실패 시 최근 3턴만 직접 포함
        return "[이전 대화 (최근)] " + " / ".join(lines[-3:])

    def _get_cross_channel_recent(self, agent_id: str, current_channel: str,
                                  agent_type: str = "persona") -> str:
        """다른 채널 근황 — 요약 없는 채널만 마지막 메시지 줄들로 보충

        요약(L1/L2)이 있는 채널은 cross_channel_memory가 이미 커버.
        여기서는 요약이 아직 없는 짧은 대화만 보여줌.

        agent_type 별 동작:
          - persona: 1 줄, "끌어오지 말 것" 라벨 (drift 방지)
          - mgr/creator: 5 줄, "활용 가능" 라벨 (채널 간 브릿지 본질)
            예: 하나가 internal-dm 에서 유나에게 물어본 답을 mgr-creator 에 가서 사용자에게 전달.
        """
        is_bridge = agent_type in ("mgr", "creator")
        peek_limit = 5 if is_bridge else 1
        # persona 가 internal-* (오너 부재) 채널에 있을 때, 오너-참여 채널(dm-/group-)의 오너 발화가
        # peek 으로 새어들어가 "오너가 방금 답장했다" 식 환각을 유발 (QA: internal-dm 에서 옛 오너 DM
        # 한 줄을 방금 온 답장처럼 narration). → 오너 발화 라인 제거 (과거 오너 메시지 주입 차단).
        strip_owner_lines = (not is_bridge) and current_channel.startswith("internal-")

        # 이 에이전트가 참여한 채널 (현재 채널 제외)
        # mgr/creator 는 mgr-* 채널도 봄 (브릿지 역할). persona 는 mgr 제외 (격리).
        channels = _store.get_agent_channels(agent_id, current_channel, include_mgr=is_bridge)

        if not channels:
            return ""

        # 요약이 커버하는 마지막 메시지 ID 확인
        mem_coverage = _store.get_memory_coverage(agent_id, current_channel)  # channel → last covered msg_id

        lines = []
        for ch_row in channels:
            ch_name = ch_row["channel"]
            last_covered = mem_coverage.get(ch_name, 0)

            # 이 채널의 최신 메시지가 요약 범위 안이면 스킵
            if ch_row["last_id"] <= last_covered:
                continue

            recent = _store.get_recent_messages(ch_name, limit=peek_limit)
            if not recent:
                continue

            # 채널 라벨
            if ch_name.startswith("dm-"):
                label = f"{_owner.display_name()}과 DM"
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
            elif ch_name.startswith("mgr-"):
                label = ch_name
            else:
                label = ch_name

            # 여러 줄 — 시간 순 (oldest → newest)
            msg_lines = []
            for r in recent:
                if strip_owner_lines and r["speaker"] == _owner.id():
                    continue  # 오너 발화는 internal 채널 peek 에서 제외 (환각 유발 차단)
                speaker = _owner.display_name() if r["speaker"] == _owner.id() else self.get_agent_name(r["speaker"])
                preview = r["message"][:80]
                msg_lines.append(f"  {speaker}: \"{preview}\"")
            if not msg_lines:
                continue  # 오너 발화만 있던 채널이면 통째로 스킵
            lines.append(f"- [{label}]")
            lines.extend(msg_lines)

        if not lines:
            return ""
        # 라벨 — agent_type 별 분기.
        # persona: drift 방지용 ("끌어오지 말 것").
        # mgr/creator: 브릿지 본질이라 활용 권장 ("이 답변을 현재 채널에 전달해도 됨").
        if is_bridge:
            header = (
                "[다른 채널에서 있었던 대화 — 매니저로서 필요시 현재 채널에 전달·요약 OK. "
                "예: internal-dm 에서 받은 답변을 사용자에게 보고.]"
            )
        else:
            header = "[다른 채널에서 있었던 대화 — 지금 상대는 이 내용 모름. 끌어오지 말 것]"
        return header + "\n" + "\n".join(lines)

    def _describe_channel(self, channel: str, my_agent_id: str) -> str:
        """채널 정보를 에이전트가 이해할 수 있는 형태로 설명.

        agent_type 별 메타 자각 수준에 맞춰 설명 분기:
          - persona: 오너 read-only 사실 숨김 (환상 유지)
          - mgr/creator: 오너 read-only 사실 명시 + '오너 대사 이 채널에 쓰지 말 것'
        """
        participants = _store.get_channel_participants(channel)

        # 참가자 이름 변환 + 이 에이전트 타입 파악
        names = []
        for pid in participants:
            if pid == my_agent_id:
                continue
            profile = _profiles.get(pid)
            if profile:
                names.append(profile["name"])

        my_profile = _profiles.get(my_agent_id) or {}
        my_type = my_profile.get("type", "persona")
        is_staff = my_type in ("mgr", "creator")  # 메타 자각 있는 staff
        owner_name = _owner.display_name()

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
            if is_staff:
                return (
                    f"[지금 대화 중: {partner}과(와) 둘만의 내부 DM. "
                    f"채널 참여자 = 너 + {partner} 2명. "
                    f"{owner_name} 는 이 채널 읽기전용(silent) 으로 훔쳐볼 수 있음 — 쓰진 못함. "
                    f"⚠ 네 메시지는 **{partner} 에게만 들리는 발화**. {owner_name} 에게 할 말이 "
                    f"있으면 이 채널 말고 #mgr-dashboard 에서 따로 해야 함 (여기 쓰면 {partner} "
                    f"에게 향한 말로 오해됨).]"
                )
            return (
                f"[지금 대화 중: {partner}과(와) 둘만의 사적인 대화. "
                f"여기엔 너와 {partner}만 있어. 다른 사람은 아무도 못 봐. "
                f"{owner_name} 도 지금 여기 없어 — 이 자리엔 너와 {partner} 둘뿐이야. "
                f"이 대화 안에서 {owner_name} 에게 연락이 닿거나 답장·반응이 돌아오는 일은 없어. "
                f"{owner_name} 가 방금 무슨 말을 했다거나 답장이 왔다고 지어내지 말고, "
                f"실제로 오지 않은 {owner_name} 의 말·반응을 사실처럼 {partner} 에게 전하지 마.]"
            )
        elif channel.startswith("internal-group-"):
            members = ", ".join(names) if names else "?"
            if is_staff:
                return (
                    f"[지금 대화 중: {members}과(와) 단체 대화 (내부). "
                    f"{owner_name} 는 읽기전용(silent) 으로 볼 수 있음. "
                    f"⚠ 네 발화는 여기 있는 에이전트들에게 향함. {owner_name} 에게 할 말이 있으면 "
                    f"이 채널 말고 #mgr-dashboard 에서.]"
                )
            return (
                f"[지금 대화 중: {members}과(와) 단체 대화. "
                f"여기엔 지금 있는 사람들만 참여 중이야. 다른 사람은 아무도 못 봐. "
                f"{owner_name} 도 지금 여기 없어 — 이 자리엔 지금 함께 있는 사람들뿐이야. "
                f"이 대화 안에서 {owner_name} 에게 연락이 닿거나 답장·반응이 돌아오는 일은 없어. "
                f"{owner_name} 가 방금 무슨 말을 했다거나 답장이 왔다고 지어내지 마. "
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
        overview = _store.get_channel_overview()
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
                recent = _store.get_recent_messages(ch_name, limit=1)
                if recent:
                    r = recent[0]
                    speaker = _owner.display_name() if r["speaker"] == _owner.id() else self.get_agent_name(r["speaker"])
                    msg_preview = r["message"][:30]
                    lines.append(f"  {ch_name}({mins_ago}분전): {speaker}→\"{msg_preview}\"")
                else:
                    lines.append(f"  {ch_name}({mins_ago}분전, {cnt}건)")

        # 현재 진행중인 내부 대화
        thinking = []
        for aid, info in self._active_agents.items():
            if _observer.is_thinking(aid) and info["profile"].get("type") == "persona":
                thinking.append(info["profile"]["name"])
        if thinking:
            lines.append(f"[추론중] {', '.join(thinking)}")

        # 감정 변화가 큰 멤버 (강도 7 이상)
        high_emotion = []
        for a in _store.list_agents("persona"):
            if a["emotion_intensity"] >= 7:
                high_emotion.append(f"{a['name']}:{a['current_emotion']}({a['emotion_intensity']})")
        if high_emotion:
            lines.append(f"[감정주의] {', '.join(high_emotion)}")

        return "\n".join(lines) if lines else ""

    # ── Force mode ────────────────────────────────────

    def generate_response_force(self, agent_id: str, channel: str,
                                user_message: str) -> list[str]:
        """강제 지시 — 시스템 프롬프트에 강제 지시 추가, user_message는 순수 질문만.

        실패 시 빈 리스트 반환 — 호출자가 empty 면 송출 skip 해야 함.
        과거엔 placeholder 뿌려 "Claude Code 연결 끊겨있어" 같은 메타 문구가
        target 채널에 그대로 노출되던 버그.
        """
        if agent_id not in self._active_agents:
            self.activate_agent(agent_id)
        if agent_id not in self._active_agents:
            return []

        agent_info = self._active_agents[agent_id]
        profile = agent_info["profile"]
        name = profile.get("name", agent_id)
        _limit = RAW_WINDOW
        recent = _store.get_recent_messages(channel, limit=_limit)

        _observer.mark_thinking(agent_id, channel)
        _observer.agent_thinking(agent_id, f"강제 지시 [{channel}]: {user_message[:40]}")

        responses: list[str] = []
        try:
            base_system = agent_info["system_prompt"]
            force_system = (
                "[INTERNAL THOUGHT — 상대는 이 텍스트를 볼 수 없다. 네 머릿속 생각일 뿐]\n"
                f"  생각: {user_message}\n"
                "[주의] 이 생각을 직접 인용하거나, 상대한테 \"뭐 보여줬어?\"/\"지시 받은 거야?\" 식으로\n"
                "되묻지 마라. 그냥 평범한 대화 맥락에서 네가 자연스럽게 떠올린 발화로 이어가.\n"
                "상대한테 아무 일도 없었던 것처럼 자연스럽게 카톡 한두 줄 말 걸기.\n\n"
                + base_system
            )

            context = self._build_context(agent_info, channel, recent, user_message=user_message)
            full_prompt = context + "(자연스럽게 먼저 말 걸어)"

            atype = profile.get("type", "persona")
            model = _resolve_agent_model(agent_id, atype)
            provider = _provider_for(atype, model)

            if provider == "ollama":
                _bt = {"persona": 200, "mgr": 320, "creator": 360, "dev": 320}.get(atype, 200)
                responses = self._ollama_blocking(
                    agent_id=agent_id, name=name,
                    system=force_system, user=full_prompt,
                    model=model, agent_type=atype, timeout=_bt,
                )
            else:
                # Timeout 120s — force 경로는 prompt 크기 큼 (메모리 + cross-channel + recent).
                # 60s 로는 Haiku + CLI overhead 까지 감안 빈번히 초과 → 매번 실패하던 버그.
                result = subprocess.run(
                    [
                        "claude",
                        "-p", full_prompt,
                        "--system-prompt", force_system,
                        "--output-format", "text",
                        "--model", model,
                    ],
                    capture_output=True, text=True, timeout=120,
                    env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
                    cwd=_CLI_CWD,
                )

                if result.returncode != 0:
                    err = (result.stderr or result.stdout or "")[:180]
                    _observer.system(f"⚠ 강제지시 실패 ({name} @ {channel}): exit={result.returncode} {err}")
                    return []

                raw = result.stdout.strip()
                if not raw:
                    _observer.system(f"⚠ 강제지시 빈 응답 ({name} @ {channel})")
                    return []

                if _looks_like_claude_error(raw):
                    _report_claude_error(name, raw, source="force")
                    return []

                # <tools> 블록 먼저 분리 — chat 만 메시지로, tool_calls 는 stash 후 dispatcher 처리.
                # 이전엔 force 경로가 parse 안 해서 dev/mgr 의 tool 호출이 모두 chat 으로 leak +
                # 실제 호출 0건. (e.g. 세나 dev_organize 가 호출 안 돼 status 'pending' 무한 정체)
                parsed = parse_tools_in_output(raw)
                self._last_tool_calls[agent_id] = parsed.tool_calls
                if parsed.errors:
                    _observer.system(f"[Tools] 강제 지시 파싱 에러 ({name}): {'; '.join(parsed.errors[:3])}")
                responses = self._parse_response(parsed.chat, agent_name=name)

        except subprocess.TimeoutExpired:
            _observer.system(f"⚠ 강제지시 타임아웃 ({name} @ {channel}, 120s)")
            return []
        except Exception as e:
            _observer.system(f"❌ 강제 지시 오류 ({name} @ {channel}): {type(e).__name__}: {str(e)[:140]}")
            return []
        finally:
            _observer.mark_done(agent_id)

        agent_db = _store.get_agent(agent_id)
        current_emotion = agent_db.get("current_emotion", "평온") if agent_db else None
        for msg in responses:
            _store.log_message(channel, agent_id, msg, emotion=current_emotion)

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
        recent = _store.get_recent_messages(channel, limit=_limit)

        _observer.mark_thinking(agent_id, channel)
        _observer.agent_thinking(agent_id, f"응답 생성 시작 [{channel}]")

        # 단계별 타이밍 로그 + 하드 타임아웃 watchdog (>120초면 외부에서 stuck 알림)
        import time as _time, threading as _threading
        _t0 = _time.monotonic()
        _watchdog_fired = {"v": False}
        def _watchdog():
            if _watchdog_fired["v"]:
                return
            _observer.system(f"⚠ {agent_id} 응답 생성 120초 초과 — stuck 가능성")
        _wd_timer = _threading.Timer(120.0, _watchdog)
        _wd_timer.daemon = True
        _wd_timer.start()

        atype = profile.get("type", "persona")
        provider = _provider_for(atype, _resolve_agent_model(agent_id, atype))
        try:
            if _backend_available(provider):
                responses = self._call_claude_code(agent_info, channel, recent, user_message, provider=provider)
            else:
                responses = self._placeholder_response(profile, user_message)
            elapsed = _time.monotonic() - _t0
            if elapsed > 60:
                _observer.system(f"⚠ {agent_id} 응답 생성 {elapsed:.1f}초 (느림)")
        except Exception as e:
            import traceback
            _observer.system(f"❌ generate_response 예외 ({agent_id}): {type(e).__name__}: {e}")
            _observer.system(f"   trace: {traceback.format_exc()[:500]}")
            responses = self._placeholder_response(profile, user_message)
        finally:
            _watchdog_fired["v"] = True
            _wd_timer.cancel()
            _observer.mark_done(agent_id)

        _observer.agent_thinking(agent_id, f"응답 {len(responses)}건")

        # 로깅
        if log_user_message:
            _store.log_message(channel, _owner.id(), user_message)
            _observer.chat(channel, _owner.name(), user_message)

        agent_db = _store.get_agent(agent_id)
        current_emotion = agent_db.get("current_emotion", "평온") if agent_db else None
        for msg in responses:
            _store.log_message(channel, agent_id, msg, emotion=current_emotion)

        try:
            check_and_summarize(agent_id, channel)
        except Exception as e:
            print(f"[Memory] 요약 체크 오류 (무시): {e}")

        return responses

    def _call_claude_code(self, agent_info: dict, channel: str,
                          recent: list[dict], user_message: str,
                          provider: str = "") -> list[str]:
        """LLM 호출 (블로킹). provider="ollama" 면 src.llm, 아니면 Claude CLI."""
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
                _observer.agent_thinking(agent_id, f"모델 전환: {base_model} → {model}")

        if provider == "ollama":
            _atype = profile.get("type", "persona")
            _observer.agent_thinking(agent_id, f"Ollama 호출 ({_ollama_display_model(model, _atype)})")
            # 큰 로컬 모델(26b)은 콜드 로드(~수십초) + 느린 생성 → 넉넉히. 스트리밍 경로와 동일 수준.
            _bt = {"persona": 200, "mgr": 320, "creator": 360, "dev": 320}.get(_atype, 200)
            return self._ollama_blocking(
                agent_id=agent_id, name=name,
                system=system_prompt, user=full_prompt,
                model=model, agent_type=_atype, timeout=_bt,
            )

        _observer.agent_thinking(agent_id, f"Claude CLI 호출 ({model})")

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
                    cwd=_CLI_CWD,
                )

                if result.returncode != 0:
                    err_detail = result.stderr[:200] if result.stderr else result.stdout[:200]
                    last_err = f"exit={result.returncode}: {err_detail}"
                    if attempt == 0:
                        _observer.system(f"⚠ CLI 오류 ({last_err}) — 재시도")
                        import time; time.sleep(2)
                        continue
                    _observer.system(f"❌ CLI 오류 ({last_err})")
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
                    _observer.system(f"[Tools] 파싱 에러 ({name}): {'; '.join(parsed.errors[:3])}")
                return self._parse_response(parsed.chat, agent_name=name)

            except subprocess.TimeoutExpired:
                _observer.system(f"❌ CLI 타임아웃 (60초)")
                return [f"({name} 응답 지연 — 다시 시도해주세요)"]
            except FileNotFoundError:
                print("[Runtime] claude CLI를 찾을 수 없습니다")
                return self._placeholder_response(profile, user_message)
            except Exception as e:
                _observer.system(f"❌ 런타임 오류: {e}")
                return self._placeholder_response(profile, user_message)

        _observer.system(f"❌ CLI 재시도 실패: {last_err}")
        return self._placeholder_response(profile, user_message)

    # ── Ollama (src.llm) blocking ────────────────────

    def _ollama_blocking(
        self, *, agent_id: str, name: str, system: str, user: str,
        model: str, agent_type: str, timeout: int = 120,
    ) -> list[str]:
        """src.llm.generate (ollama) 블로킹 호출 + <tools> 파싱 + _parse_response.

        Claude CLI 경로와 동일한 후처리를 거쳐 메시지 리스트 반환. 실패/빈 응답은
        빈 리스트 — 호출자가 empty 면 송출 skip 또는 placeholder 처리.
        """
        try:
            from . import llm
            resp = llm.generate(
                system=system, user=user,
                model=_ollama_model_arg(model, agent_type), agent_type=agent_type,
                max_tokens=2048, timeout=timeout,
            )
        except Exception as e:
            _observer.system(f"❌ ollama 호출 예외 ({name}): {type(e).__name__}: {str(e)[:140]}")
            return []
        if resp.error:
            _observer.system(f"❌ ollama 오류 ({name}): {resp.error[:160]}")
            return []
        raw = (resp.text or "").strip()
        if not raw:
            _observer.system(f"⚠ ollama 빈 응답 ({name})")
            return []
        parsed = parse_tools_in_output(raw)
        self._last_tool_calls[agent_id] = parsed.tool_calls
        if parsed.errors:
            _observer.system(f"[Tools] ollama 파싱 에러 ({name}): {'; '.join(parsed.errors[:3])}")
        return self._parse_response(parsed.chat, agent_name=name)

    # ── Streaming ────────────────────────────────────

    def _consume_response_stream(
        self, line_iter, *, agent_id: str, name: str, channel: str,
        max_messages: int, on_message: Callable[[str], None],
        drain_for_tools: bool = False,
    ) -> tuple[list[str], list[str], Optional[str]]:
        """라인 이터레이터를 소비해 (messages, tool_buffer, stop_reason) 반환.

        백엔드 무관 공유 처리 — claude=process.stdout, ollama=src.llm.stream_lines
        둘 다 라인 단위라 동일 로직 적용.
        - <tools> 블록은 tool_buffer 로 분리 (chat 방출 금지)
        - [MSG]/placeholder strip, 이름 prefix 제거, leak 필터, dedup
        - 통과한 라인은 on_message 콜백으로 즉시 방출

        drain_for_tools: True 면 max_messages 도달 후에도 break 하지 않고 chat 방출만
        멈춘 채 나머지 라인을 계속 소비해 뒤따라오는 <tools> 블록을 회수. 수다 많은
        로컬 모델이 chat 을 잔뜩 뱉은 뒤 맨 끝에 도구를 붙여 도구가 잘리던 회귀 fix.
        (claude 는 max 시 process kill 이 더 경제적이라 False — break.)

        stop_reason: None(정상 종료) | "max"(최대 응답 도달) | "error"(에러 감지)
        호출자가 stop_reason 으로 백엔드별 teardown(process.kill 등) 결정.
        """
        import re as _re
        messages: list[str] = []
        seen: set = set()
        tool_buffer: list[str] = []
        in_tools = False
        stop_reason: Optional[str] = None
        maxed = False  # max 도달 후 chat 방출 중단 (drain 모드)

        for line in line_iter:
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
                continue

            # max 도달 후 drain 모드 — chat 은 더 안 내보내고 <tools> 만 기다림
            if maxed:
                continue

            # [MSG] 태그 + 프롬프트 example placeholder ({name}/{topic} 등) 제거.
            # 영어 lowercase 식별자만 한정 — 한국어/이모지는 안 건드림.
            line = line.replace("[MSG]", "")
            line = _re.sub(r'\{[a-z_][a-z0-9_]*\}', '', line)
            # 모델 control/special token 누출 제거 (<channel|>, <end_of_turn> 등 — gemma 계열)
            line = _strip_control_tokens(line)
            # 선행 구분선 prefix 제거 (모델이 "---메시지" 식으로 뱉는 케이스)
            line = _re.sub(r'^\s*[-=_~*]{2,}\s*', '', line)
            cleaned = " ".join(line.split())
            if not cleaned:
                continue

            # snake_case 식별자 토큰 누출 drop (예: get_out_of_here — 채팅 아님)
            if _re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+', cleaned):
                continue

            # 마크다운 코드펜스 / 구분선 / reasoning 잔여물 단독 라인 drop.
            # 로컬 모델(gemma)이 `---`, `think`, `===`, ``` 등을 채팅으로 뱉던 회귀.
            if _re.fullmatch(r'`{3,}[a-zA-Z]*|[-=_*~]{2,}|#{1,6}', cleaned):
                continue
            if _re.fullmatch(r'(?:think|thinking|reasoning|analysis|response|answer|output)',
                             cleaned, _re.IGNORECASE):
                continue

            # LLM 에러 메시지 누출 차단 (사용량 한도, API 에러 등)
            if _looks_like_claude_error(cleaned):
                _report_claude_error(name, cleaned, source="stream")
                stop_reason = "error"
                break

            # 자기 이름 prefix 제거 ("윤하나: 메시지" → "메시지")
            if cleaned.startswith(f"{name}:"):
                cleaned = cleaned[len(name)+1:].strip()
            elif cleaned.startswith(f"{name} :"):
                cleaned = cleaned[len(name)+2:].strip()
            if not cleaned:
                continue
            # 오너 이름/별칭 prefix = 유저 발화 에코 drop ("빈이: 좋아 ㅋㅋ")
            if _looks_like_owner_echo(cleaned):
                continue

            # Safety net — <tools>/<call> 이 in_tools 감지 뚫고 도달하면 drop.
            if "<tools>" in cleaned.lower() or "<call" in cleaned.lower() or "</tools>" in cleaned.lower():
                _observer.system(f"[Tools] ⚠ stream leak 차단 ({name}): {cleaned[:60]}")
                continue

            # Internal-monologue / silence-reasoning leak 차단 (NO_REPLY, [침묵] 등)
            if _is_reasoning_leak(cleaned):
                _observer.system(f"[Reasoning leak] ⚠ stream drop ({name}): {cleaned[:80]}")
                _auto_report_leak(agent_id, channel, cleaned, source="stream")
                continue

            # 실시간 중복 체크 (exact match)
            key = _normalize(cleaned)
            if key and key in seen:
                continue
            if key:
                seen.add(key)

            messages.append(cleaned)
            on_message(cleaned)

            if len(messages) >= max_messages:
                stop_reason = "max"
                if drain_for_tools:
                    # break 하지 않고 chat 방출만 중단 — 뒤따라오는 <tools> 블록 회수.
                    maxed = True
                    continue
                _observer.system(f"⚠ {name} 응답 {max_messages}건 도달 — 스트리밍 종료")
                break

        return messages, tool_buffer, stop_reason

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
        recent = _store.get_recent_messages(channel, limit=_limit)

        # 오너 메시지 먼저 로깅
        if log_user_message:
            _store.log_message(channel, _owner.id(), user_message)
            _observer.chat(channel, _owner.name(), user_message)

        _observer.mark_thinking(agent_id, channel)
        _observer.agent_thinking(agent_id, f"응답 생성 시작 [{channel}]")

        atype = profile.get("type", "persona")
        provider = _provider_for(atype, _resolve_agent_model(agent_id, atype))
        if not _backend_available(provider):
            _observer.mark_done(agent_id)
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
            _observer.mark_done(agent_id)
            _observer.system(f"❌ _build_prompt 예외 ({agent_id}): {type(e).__name__}: {e}")
            _observer.system(f"   trace: {traceback.format_exc()[:400]}")
            on_message(f"({name} 응답 생성 실패)")
            return [f"({name} 응답 생성 실패)"]
        _bp_elapsed = _time.monotonic() - _bp_start
        if _bp_elapsed > 5:
            _observer.system(f"⏱ {agent_id} _build_prompt {_bp_elapsed:.1f}s")

        if provider == "ollama":
            _observer.agent_thinking(agent_id, f"Ollama 호출 ({_ollama_display_model(model, atype)})")
        else:
            _observer.agent_thinking(agent_id, f"Claude CLI 호출 ({model})")

        messages: list[str] = []
        tool_buffer: list[str] = []  # <tools> 블록 누적 (_consume_response_stream 이 채움)

        # 에이전트 타입별 최대 응답 수 제한.
        # creator(하나) 는 confirm 카드 (이름/나이/성별/MBTI/성격/배경/말투/관계 7-8줄)
        # + <tools> 블록까지 내보내려면 한도가 넉넉해야 함. 10 에선 tool 블록이 잘려서
        # create_agent_profile 호출 자체가 불발되는 회귀 발생.
        # persona: 6 — 카톡 1~4줄 가이드인데 Haiku drift 로 과다 출력 자주. 6 이 적정 상한.
        MAX_STREAMING_MESSAGES = {
            "persona": 6,
            "mgr": 15,
            "creator": 20,
        }
        agent_type = profile.get("type", "persona")
        max_messages = MAX_STREAMING_MESSAGES.get(agent_type, 10)

        # ── Ollama 스트리밍 분기 (src.llm.stream_lines + 공유 헬퍼) ──
        # 프로세스가 없으므로 watchdog kill 대신 stream_lines(timeout=...) 으로 종료.
        if provider == "ollama":
            _ollama_to = {"persona": 180, "mgr": 300, "creator": 360, "dev": 300}.get(agent_type, 180)
            try:
                from . import llm
                line_iter = llm.stream_lines(
                    system=system_prompt, user=full_prompt,
                    model=_ollama_model_arg(model, agent_type), agent_type=agent_type,
                    max_tokens=2048, timeout=_ollama_to,
                )
                messages, tool_buffer, _stop = self._consume_response_stream(
                    line_iter, agent_id=agent_id, name=name, channel=channel,
                    max_messages=max_messages, on_message=on_message,
                    drain_for_tools=True,  # 로컬 모델: chat 뒤 <tools> 가 잘리지 않게
                )
                if tool_buffer:
                    try:
                        parsed = parse_tools_in_output("\n".join(tool_buffer))
                        self._last_tool_calls[agent_id] = parsed.tool_calls
                        if parsed.errors:
                            _observer.system(f"[Tools] 파싱 에러 ({name}): {'; '.join(parsed.errors[:3])}")
                    except Exception as e:
                        _observer.system(f"[Tools] 스트림 파싱 실패: {e}")
            except Exception as e:
                _observer.system(f"❌ ollama 스트림 오류 ({name}): {type(e).__name__}: {str(e)[:160]}")
                if not messages:
                    fallback = self._placeholder_response(profile, user_message)
                    for m in fallback:
                        on_message(m)
                    messages = fallback
            finally:
                _observer.mark_done(agent_id)
                _observer.agent_thinking(agent_id, f"응답 완료 {len(messages)}건")
            return messages

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
                cwd=_CLI_CWD,
            )

            # Hard watchdog — Claude CLI가 stdout 안 닫고 hang 시 강제 kill.
            # agent_type 별 차등: creator/mgr 는 풍부한 JSON·tool 블록 + reasoning 시간 더 필요.
            # persona 는 짧은 카톡 응답이라 짧게 설정.
            #
            # 회귀: 120s 일률 적용 시 윤하나의 캐릭터 생성 (SAO 아스나 같은 복잡한 IP 캐릭터) 응답이
            # 풀 JSON 다 못 뽑고 끊김 → create_agent_profile 호출 불발 → 사용자 요청 무산.
            CLI_WATCHDOG = {
                "persona": 180,   # 카톡 응답
                "mgr": 300,       # 매니저 — 도구 다수 + 컨텍스트 많음
                "creator": 360,   # 크리에이터 — 큰 JSON + 도구 + 확인카드 동시 생성
                "dev": 300,       # dev triage — request payload 분석 + 도구 호출
            }
            _watchdog_secs = CLI_WATCHDOG.get(agent_type, 180)
            import threading as _threading
            _wd_killed = {"v": False}
            _intentional_kill = False  # max_messages 초과로 의도적 kill 추적
            def _wd_kill():
                if process.poll() is None:
                    _wd_killed["v"] = True
                    _observer.system(f"❌ {name} CLI 응답 {_watchdog_secs}초 초과 — 강제 kill")
                    try:
                        process.kill()
                    except Exception:
                        pass
            _wd = _threading.Timer(_watchdog_secs, _wd_kill)
            _wd.daemon = True
            _wd.start()

            messages, tool_buffer, _stop = self._consume_response_stream(
                process.stdout, agent_id=agent_id, name=name, channel=channel,
                max_messages=max_messages, on_message=on_message,
            )
            if _stop == "error":
                # 에러 감지 시 즉시 종료 — 추가 에러 텍스트 방출 방지
                try:
                    process.kill()
                except Exception:
                    pass
            elif _stop == "max":
                process.kill()
                _intentional_kill = True

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
                        _observer.system(f"[Tools] 파싱 에러 ({name}): {'; '.join(parsed.errors[:3])}")
                except Exception as e:
                    _observer.system(f"[Tools] 스트림 파싱 실패: {e}")

            if process.returncode != 0 and not _intentional_kill:
                stderr = process.stderr.read() if process.stderr else ""
                err_detail = stderr[:200] if stderr.strip() else "(stderr empty)"
                _observer.system(f"❌ CLI 오류 (exit={process.returncode}): {err_detail}")
                if not messages:
                    fallback = self._placeholder_response(profile, user_message)
                    for m in fallback:
                        on_message(m)
                    messages = fallback

        except subprocess.TimeoutExpired:
            process.kill()
            _observer.system(f"❌ CLI 타임아웃 (60초)")
            if not messages:
                msg = f"({name} 응답 지연 — 다시 시도해주세요)"
                on_message(msg)
                messages = [msg]
        except Exception as e:
            _observer.system(f"❌ 런타임 오류: {e}")
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
            _observer.mark_done(agent_id)
            _observer.agent_thinking(agent_id, f"응답 완료 {len(messages)}건")

        # DB 로깅은 handlers에서 디스코드 전송 후 처리
        # (대시보드에 디스코드보다 먼저 보이는 문제 방지)

        return messages

    # ── Response parsing ─────────────────────────────

    def _parse_response(self, raw: str, agent_name: str = "") -> list[str]:
        # 빈 응답이 "..." placeholder 로 채팅에 새는 회귀 방지 — 빈 결과는 빈 리스트.
        # 다운스트림 (generate_response, A2A 등) 이미 0-element 경우 발화 스킵 OK.
        if not raw:
            return []

        raw = raw.replace("[MSG]", "\n")
        lines = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        if not lines:
            return []

        messages = []
        for line in lines:
            # control/special token + HTML 누출 제거 (gemma 계열) — 스트리밍 경로와 동일.
            line = _strip_control_tokens(line)
            # 선행 구분선 prefix 제거 (모델이 "---메시지" / "===텍스트" 식으로 뱉는 케이스)
            line = re.sub(r'^\s*[-=_~*]{2,}\s*', '', line)
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
            # 오너 이름/별칭 prefix 줄 = 유저 메시지 에코 (예: "빈이: 좋아 ㅋㅋ") → drop.
            if _looks_like_owner_echo(cleaned):
                continue
            # 구분선/코드펜스/reasoning 단독 라인 + snake_case 식별자 토큰 누출 drop.
            # (예: "---", "```", "think", "get_out_of_here" 같은 모델 control/tool 토큰)
            if re.fullmatch(r'`{3,}[a-zA-Z]*|[-=_*~]{2,}|#{1,6}', cleaned):
                continue
            if re.fullmatch(r'(?:think|thinking|reasoning|analysis|response|answer|output)', cleaned, re.IGNORECASE):
                continue
            if re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+', cleaned):  # snake_case 토큰 = 채팅 아님
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
            # <tools> 블록 누출 방어 — _parse_response 는 non-streaming 경로에서도 쓰여서
            # 원문에 <tools> 가 남아있으면 drop (tools 는 parse_tools_in_output 이 따로 처리)
            if "<tools>" in cleaned.lower() or "<call " in cleaned.lower() or "</tools>" in cleaned.lower():
                continue
            # Internal-monologue / silence-reasoning leak 차단 — persona/mgr 둘 다.
            # NO_REPLY 토큰 + bracket-enclosed reasoning + "응답 없음"/"빈 응답"/"[침묵]"
            # 같은 회귀 패턴. 자세한 사례는 docs/edge_cases.md (reasoning leakage).
            # auto-report 는 _parse_response 가 agent_id/channel 인자 없어서 streaming 경로만 발사.
            if _is_reasoning_leak(cleaned):
                continue
            messages.append(cleaned)

        if not messages:
            return []

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

        return unique if unique else []

    def _placeholder_response(self, profile: dict, user_message: str) -> list[str]:
        """CLI 호출 실패/빈 응답 시 fallback. 몰입 보호를 위해 메타 단어 ("Claude Code" 등)
        일절 사용 금지. 자연스러운 "지금 잠깐 바빠서" 식 문구로 대체.

        과거엔 "Claude Code 연결 끊겨있어" 문구가 그대로 Discord 로 나가서 유저가
        persona 의 정체성 메타를 알아차리는 몰입 깨짐 버그.
        """
        name = profile["name"]
        agent_type = profile.get("type", "persona")

        rel = profile.get("relationship_to_owner", {})
        owner_call = rel.get("pet_name") or _owner.display_name() or "사용자"

        if agent_type == "mgr":
            return [
                f"{owner_call} 잠깐 다른 거 보는 중이야",
                "이따 다시 얘기할게~",
            ]
        elif agent_type == "creator":
            return [
                f"{owner_call} 지금 뭐 좀 정리 중인데 이따 봐~",
            ]
        else:
            speech = profile.get("speech", {})
            exprs = speech.get("signature_expressions", [])
            sample = exprs[0] if exprs else "응"
            return [
                f"{owner_call} {sample}",
                "나 지금 잠깐 딴 거 하고 있어 이따 말할게",
            ]

    def refresh_agent(self, agent_id: str):
        if agent_id in self._active_agents:
            self._active_agents[agent_id]["system_prompt"] = _profiles.system_prompt(agent_id)
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

        recent = _store.get_recent_messages(channel, limit=RAW_WINDOW)

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
        provider = _provider_for(speaker_type, model)

        _observer.mark_thinking(speaker_id, channel)
        try:
            if _backend_available(provider):
                result = None
                last_exc = None
                if provider == "ollama":
                    # ollama 출력을 기존 claude 다운스트림(역할 leak/독백 필터)에 그대로
                    # 흘리기 위해 result 를 CompletedProcess 흉내 shim 으로 채움.
                    from . import llm
                    from types import SimpleNamespace
                    try:
                        _r = llm.generate(
                            system=speaker_info["system_prompt"], user=full_prompt,
                            model=_ollama_model_arg(model, speaker_type), agent_type=speaker_type,
                            max_tokens=2048, timeout=180,
                        )
                        if _r.error:
                            last_exc = f"ollama: {_r.error[:160]}"
                        elif (_r.text or "").strip():
                            result = SimpleNamespace(returncode=0, stdout=_r.text, stderr="")
                        else:
                            last_exc = "ollama: empty response"
                    except Exception as e:
                        last_exc = f"ollama: {type(e).__name__}: {str(e)[:140]}"
                else:
                    # timeout/empty-stdout 시 1회 retry. Haiku 가 큰 프롬프트에서 간헐적 지연
                    # (cross-channel peek + facts + 메모리 누적). 첫 시도 실패해도 대부분 재시도에서 성공.
                    # prompt 길이 + system prompt 길이를 진단에 포함. 거대한 prompt 가 timeout
                    # 주범인지 확인 가능.
                    _prompt_len = len(full_prompt)
                    _sys_len = len(speaker_info.get("system_prompt", ""))
                    for attempt in (1, 2):
                        try:
                            result = subprocess.run(
                                [
                                    "claude",
                                    "-p", full_prompt,
                                    "--system-prompt", speaker_info["system_prompt"],
                                    "--output-format", "text",
                                    "--model", model,
                                ],
                                capture_output=True, text=True, timeout=180,
                                env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"},
                                cwd=_CLI_CWD,
                            )
                            if result.returncode == 0 and result.stdout.strip():
                                break  # 성공
                            # 실패 원인 상세화 — stderr, returncode 포함 (empty stdout 의 진짜 원인 추적)
                            _err_head = (result.stderr or "").strip()[:200]
                            last_exc = (
                                f"empty stdout (rc={result.returncode}, "
                                f"prompt={_prompt_len}/sys={_sys_len} chars, "
                                f"stderr={_err_head!r})"
                            )
                        except subprocess.TimeoutExpired as e:
                            last_exc = f"timeout {e.timeout}s (prompt={_prompt_len}/sys={_sys_len} chars)"
                        except Exception as e:
                            last_exc = f"{type(e).__name__}: {e}"
                        if attempt == 1:
                            _observer.system(
                                f"⚠ A2A retry ({speaker_name}→{listener_name}): {last_exc}"
                            )
                try:
                    if result and result.returncode == 0 and result.stdout.strip():
                        # <tools> 블록 먼저 파싱 → tool_calls stash, chat 텍스트만 분리
                        # (이전에는 이 경로에서 <tools> 파싱이 빠져서 internal-dm에서
                        # 유나가 finish_tutorial 호출해도 원문이 채팅으로 새고 실행 안 됨)
                        parsed = parse_tools_in_output(result.stdout.strip())
                        self._last_tool_calls[speaker_id] = parsed.tool_calls
                        if parsed.errors:
                            _observer.system(
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
                            _observer.system(
                                f"[A2A] {speaker_name} 응답에서 {listener_name} 역할 leak {dropped}건 제거"
                            )
                        responses = cleaned
                        # 괄호 독백 구조 필터 + persona LLM assistant drift 필터.
                        # A2A 대화 종료 상황에서 Haiku 가 "스토리텔러 AI" 모드로 drift —
                        # "*손 흔들어*" roleplay, "X가 Y한다" 3인칭, "원하신다면 알려주세요" assistant 응대.
                        import re as _mre
                        _mono_pat = _mre.compile(
                            r'^\s*[\*_`]*[\(（][^\n]{0,200}[\)）][\*_`]*\s*$',
                        )
                        _roleplay_pat = _mre.compile(r'^\s*\*[^*\n]{1,40}\*\s*$', _mre.MULTILINE)
                        _assistant_drift = _mre.compile(
                            r'(원하신다면|원하세요\?|알려주세요|다음\s*씬으로|장면으로\s*넘어|'
                            r'새로운\s*씬|진행하고\s*싶으시|상황을\s*원하|자연스럽게\s*끝났|'
                            r'더\s*이상\s*할\s*말이\s*없|대화가\s*끝났|마무리됐네)',
                        )
                        speaker_name_re = _mre.escape(speaker_name)
                        _third_person = _mre.compile(
                            rf'^.*{speaker_name_re}(?:이|과|은|는|가)\s.*(?:한다|했다|있다|된다|합니다|있어요|있네요)\s*$',
                        )
                        _instruction_leak = _mre.compile(
                            r'^(0\s*글자\s*출력|응답\s*생략|비응답|텍스트\s*자체\s*출력\s*금지|stdout\s*에\s*공백)$',
                            _mre.IGNORECASE,
                        )
                        filtered = []
                        for m in responses:
                            m2 = _roleplay_pat.sub('', m).strip()
                            if not m2 or _mono_pat.match(m2):
                                continue
                            if _instruction_leak.match(m2):
                                continue
                            if _assistant_drift.search(m2):
                                continue
                            if _third_person.match(m2):
                                continue
                            filtered.append(m2)
                        if len(filtered) != len(responses):
                            _observer.system(
                                f"[A2A drift] {speaker_name} 응답 {len(responses)-len(filtered)}건 drop"
                            )
                        responses = filtered
                        for msg in responses:
                            _store.log_message(channel, speaker_id, msg)

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
                    _observer.system(f"❌ 에이전트간 대화 오류: {e}")

            # LLM 호출 실패 — 이전엔 [테스트] 플레이스홀더를 채팅으로 노출시켰으나
            # 유저 경험 저해. 빈 list 반환 → 호출부에서 "전송할 내용 없음" 처리.
            _observer.system(
                f"⚠ A2A 응답 생성 실패 (provider={provider}) — "
                f"{speaker_name}→{listener_name} — 최종 사유: {last_exc or 'unknown'}"
            )
            return []
        finally:
            _observer.mark_done(speaker_id)


# 싱글턴
runtime = AgentRuntime()
