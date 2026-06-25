"""첫 실행 setup wizard 백엔드 — 설정 상태 판정 + .env 기록 + admin 부트스트랩.

흐름:
  - `is_configured()` False → run.sh/run.bat 가 브라우저를 `/setup` 으로 연다.
  - 사용자가 모델 모드(claude / hybrid / local) + admin 비번 입력.
  - `apply_setup()` 가 루트 `.env` 기록 + 프로세스 env 즉시 반영 + admin 생성 + 마커.
  - 이후 `is_configured()` True → /setup 비활성(리다이렉트), /api/setup 403.

비용 정직성: 무료 런타임 = 로컬 모델(Ollama). Claude 백엔드 에이전트는 metered
API 크레딧을 쓴다(headless `claude -p` 는 구독 무료가 아님). 그래서 setup 에서
월 상한(GLIMI_MONTHLY_CAP_USD)을 받고, 권장값은 hybrid (페르소나=로컬, mgr/creator/dev=claude).
"""
import json as _json
import os
from pathlib import Path
from typing import Optional

from . import accounts
from .config import DATA_DIR, PROJECT_ROOT

SETUP_MARKER = DATA_DIR / ".setup_complete"
# 기본 루트 .env. GLIMI_ENV_FILE 로 override (테스트 격리 / 커스텀 위치).
ENV_PATH = Path(os.environ.get("GLIMI_ENV_FILE") or (PROJECT_ROOT / ".env"))

# 모드: claude(전부 Claude) | hybrid(페르소나=로컬, 나머지=Claude, 권장) | local(전부 Ollama)
# 레거시 별칭 'cloud' → 'claude' 로 매핑(구버전 페이로드 호환).
_VALID_BACKENDS = ("claude", "hybrid", "local")
_VALID_TIERS = ("lite", "standard", "quality")
DEFAULT_MONTHLY_CAP_USD = 20

# Hybrid 라우팅: 페르소나(최다 호출자) = 로컬 Ollama, 정체성/온보딩 품질이
# 중요한 mgr/creator/dev = Claude. Glimi 느낌을 유지하는 가장 저렴한 구성.
_HYBRID_AGENT_MAP = {
    "mgr": "claude",
    "creator": "claude",
    "dev": "claude",
    "persona": "ollama",
    "_default": "ollama",
}


def backend_mode_to_env(
    mode: str,
    tier: str = "standard",
    cap: int = DEFAULT_MONTHLY_CAP_USD,
    *,
    has_key: bool = False,
) -> dict[str, str]:
    """모드 → 기록할 .env 키 dict (위저드 드리프트 방지용 단일 진실).

    두 위저드(코어 first-run · 커뮤니티별)가 모두 이 함수를 호출해 같은 키를
    만든다. `has_key` 는 Claude API 키 입력 여부(현재는 시그니처 통일용 — 키
    자체는 호출부가 따로 기록한다).

    반환 키 (모드별):
      claude → GLIMI_LLM_BACKEND="" (기본 claude), GLIMI_MONTHLY_CAP_USD
      hybrid → GLIMI_LLM_AGENT_MAP(JSON), GLIMI_LOCAL_TIER, GLIMI_MONTHLY_CAP_USD
      local  → GLIMI_LLM_BACKEND="ollama", GLIMI_LOCAL_TIER (cap 없음, 전부 $0)
    """
    mode = (mode or "").strip().lower()
    if mode == "cloud":  # 레거시 별칭
        mode = "claude"
    if mode not in _VALID_BACKENDS:
        raise ValueError("모드는 claude / hybrid / local 중 하나여야 합니다.")

    tier = (tier or "standard").strip().lower()
    if mode in ("hybrid", "local") and tier not in _VALID_TIERS:
        raise ValueError("티어는 lite / standard / quality 중 하나여야 합니다.")

    try:
        cap_i = int(cap)
    except (TypeError, ValueError):
        cap_i = DEFAULT_MONTHLY_CAP_USD
    if cap_i < 0:
        cap_i = DEFAULT_MONTHLY_CAP_USD

    out: dict[str, str] = {}
    if mode == "claude":
        # claude = 기본 백엔드. 로컬 강제 해제 + 월 상한.
        out["GLIMI_LLM_BACKEND"] = ""
        out["GLIMI_MONTHLY_CAP_USD"] = str(cap_i)
    elif mode == "hybrid":
        # 페르소나=ollama, mgr/creator/dev=claude. VALID JSON 으로 직렬화.
        out["GLIMI_LLM_AGENT_MAP"] = _json.dumps(_HYBRID_AGENT_MAP, separators=(",", ":"))
        out["GLIMI_LOCAL_TIER"] = tier
        out["GLIMI_MONTHLY_CAP_USD"] = str(cap_i)
    else:  # local
        out["GLIMI_LLM_BACKEND"] = "ollama"
        out["GLIMI_LOCAL_TIER"] = tier
        # local = 전부 $0 → 상한 안 씀.
    return out


def claude_creds_available(api_key: str = "") -> bool:
    """Claude 사용 가능 여부 — API 키(입력/환경) 또는 작동하는 claude CLI 로그인.
    steering 용: claude/hybrid 선택인데 둘 다 없으면 경고/유도."""
    if (api_key or "").strip():
        return True
    if (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return True
    try:
        from glimi.llm import find_claude
        return find_claude() is not None
    except Exception:
        return False


def is_configured() -> bool:
    """설정 완료 여부. 마커가 있거나 이미 계정이 존재하면 완료로 본다.
    (위저드 이전부터 쓰던 기존 설치는 계정이 있으니 위저드를 안 본다.)"""
    if SETUP_MARKER.exists():
        return True
    try:
        return bool(accounts.list_accounts())
    except Exception:
        return False


def mark_configured() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETUP_MARKER.write_text("ok\n", encoding="utf-8")


def upsert_env(key: str, value: str, path: Optional[Path] = None) -> None:
    """루트 .env 에 KEY=value 를 추가/갱신. 주석/다른 줄은 보존.

    path 기본값은 호출 시점의 모듈 ENV_PATH (테스트가 monkeypatch 로 바꿀 수 있게
    — 함수 정의 시점에 고정되지 않도록 None 디폴트 + 런타임 조회)."""
    if path is None:
        path = ENV_PATH
    line = f"{key}={value}"
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    out, replaced = [], False
    for ln in lines:
        stripped = ln.lstrip()
        if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
            out.append(line)
            replaced = True
        else:
            out.append(ln)
    if not replaced:
        out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def apply_setup(
    *,
    backend: str,
    admin_password: str,
    api_key: str = "",
    use_cli: bool = False,
    tier: str = "standard",
    monthly_cap_usd: int = DEFAULT_MONTHLY_CAP_USD,
) -> dict:
    """위저드 입력을 적용. 검증 실패 시 ValueError.
    반환: {"redirect": "...", "needs_local_download": bool, "warnings": [...]}"""
    backend = (backend or "").strip().lower()
    if backend == "cloud":  # 레거시 별칭
        backend = "claude"
    if backend not in _VALID_BACKENDS:
        raise ValueError("모드는 claude / hybrid / local 중 하나여야 합니다.")
    if len((admin_password or "").strip()) < 4:
        raise ValueError("admin 비밀번호는 4자 이상이어야 합니다.")

    key = (api_key or "").strip()
    if backend in ("claude", "hybrid") and not key and not use_cli:
        raise ValueError("Claude 사용 모드는 API 키를 입력하거나 claude CLI 사용을 선택하세요.")

    # Hybrid/Local 은 페르소나(또는 전부)가 Ollama 라 로컬 모델 다운로드가 필요하다.
    needs_local_download = backend in ("hybrid", "local")
    warnings: list[str] = []

    # ── 공유 헬퍼로 env 키 산출 (위저드 드리프트 방지) ──
    env_keys = backend_mode_to_env(
        backend, tier, monthly_cap_usd, has_key=bool(key),
    )
    for k, v in env_keys.items():
        upsert_env(k, v)
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    if key:
        upsert_env("ANTHROPIC_API_KEY", key)
        os.environ["ANTHROPIC_API_KEY"] = key  # 실행 중 프로세스에도 즉시 반영

    # ── 정직한 유도(graceful steering) — 잘못된 설정을 조용히 쓰지 않는다 ──
    if backend in ("claude", "hybrid") and not claude_creds_available(key):
        # 키도 없고 작동하는 claude CLI 로그인도 없음 → 매 Claude 턴이 placeholder 로
        # 떨어진다. 차라리 Local-only 를 권한다(경고).
        warnings.append(
            "Claude 자격 증명이 없습니다(API 키 없음 + claude CLI 로그인 없음). "
            "Claude 턴이 모두 placeholder 로 떨어질 수 있어요 — "
            "Local-only 모드를 권합니다."
        )

    # admin 계정 생성 — bootstrap 이 GLIMI_ADMIN_PASSWORD 를 읽는다.
    os.environ["GLIMI_ADMIN_PASSWORD"] = admin_password.strip()
    accounts.bootstrap()
    os.environ.pop("GLIMI_ADMIN_PASSWORD", None)

    mark_configured()
    return {
        "redirect": "/login?next=/",
        "needs_local_download": needs_local_download,
        "warnings": warnings,
    }
