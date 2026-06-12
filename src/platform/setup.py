"""첫 실행 setup wizard 백엔드 — 설정 상태 판정 + .env 기록 + admin 부트스트랩.

흐름:
  - `is_configured()` False → run.sh/run.bat 가 브라우저를 `/setup` 으로 연다.
  - 사용자가 모델 백엔드(클라우드/로컬) + admin 비번 (+ 선택 Discord 토큰) 입력.
  - `apply_setup()` 가 루트 `.env` 기록 + 프로세스 env 즉시 반영 + admin 생성 + 마커.
  - 이후 `is_configured()` True → /setup 비활성(리다이렉트), /api/setup 403.
"""
import os
from pathlib import Path
from typing import Optional

from . import accounts
from .config import DATA_DIR, PROJECT_ROOT

SETUP_MARKER = DATA_DIR / ".setup_complete"
# 기본 루트 .env. GLIMI_ENV_FILE 로 override (테스트 격리 / 커스텀 위치).
ENV_PATH = Path(os.environ.get("GLIMI_ENV_FILE") or (PROJECT_ROOT / ".env"))

_VALID_BACKENDS = ("cloud", "local")
_VALID_TIERS = ("lite", "standard", "quality")


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


def upsert_env(key: str, value: str, path: Path = ENV_PATH) -> None:
    """루트 .env 에 KEY=value 를 추가/갱신. 주석/다른 줄은 보존."""
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
    discord_token: str = "",
) -> dict:
    """위저드 입력을 적용. 검증 실패 시 ValueError.
    반환: {"redirect": "...", "needs_local_download": bool}"""
    backend = (backend or "").strip().lower()
    if backend not in _VALID_BACKENDS:
        raise ValueError("백엔드는 cloud 또는 local 이어야 합니다.")
    if len((admin_password or "").strip()) < 4:
        raise ValueError("admin 비밀번호는 4자 이상이어야 합니다.")

    needs_local_download = False

    if backend == "cloud":
        key = (api_key or "").strip()
        if not key and not use_cli:
            raise ValueError("API 키를 입력하거나 claude CLI 사용을 선택하세요.")
        if key:
            upsert_env("ANTHROPIC_API_KEY", key)
            os.environ["ANTHROPIC_API_KEY"] = key  # 실행 중 프로세스에도 즉시 반영
        # 클라우드 선택 시 로컬 백엔드 강제 해제
        upsert_env("GLIMI_LLM_BACKEND", "")
        os.environ.pop("GLIMI_LLM_BACKEND", None)
    else:  # local
        tier = (tier or "standard").strip().lower()
        if tier not in _VALID_TIERS:
            raise ValueError("티어는 lite / standard / quality 중 하나여야 합니다.")
        upsert_env("GLIMI_LLM_BACKEND", "ollama")
        upsert_env("GLIMI_LOCAL_TIER", tier)
        os.environ["GLIMI_LLM_BACKEND"] = "ollama"
        os.environ["GLIMI_LOCAL_TIER"] = tier
        needs_local_download = True  # 실제 모델 다운로드는 run.sh --local-models 가 처리

    if discord_token.strip():
        upsert_env("DISCORD_BOT_TOKEN", discord_token.strip())
        os.environ["DISCORD_BOT_TOKEN"] = discord_token.strip()

    # admin 계정 생성 — bootstrap 이 GLIMI_ADMIN_PASSWORD 를 읽는다.
    os.environ["GLIMI_ADMIN_PASSWORD"] = admin_password.strip()
    accounts.bootstrap()
    os.environ.pop("GLIMI_ADMIN_PASSWORD", None)

    mark_configured()
    return {"redirect": "/login?next=/", "needs_local_download": needs_local_download}
