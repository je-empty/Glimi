"""플랫폼 전역 설정 — 경로, 비밀키, 세션 파라미터."""
import os
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 기본 PROJECT_ROOT/data. GLIMI_DATA_DIR 로 override (멀티 인스턴스 / 테스트 격리).
DATA_DIR = Path(os.environ.get("GLIMI_DATA_DIR") or (PROJECT_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

PLATFORM_DB_PATH = DATA_DIR / "platform.db"
SECRET_KEY_PATH = DATA_DIR / ".secret_key"

SESSION_COOKIE_NAME = "glimi_session"
SESSION_MAX_AGE_SEC = 60 * 60 * 24 * 7  # 7일

DEFAULT_HOST = os.environ.get("GLIMI_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("GLIMI_PORT", "8000"))


def get_secret_key() -> str:
    """세션 서명 비밀키. 최초 실행 시 생성·파일 저장, 이후 재사용."""
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_urlsafe(48)
    SECRET_KEY_PATH.write_text(key)
    try:
        os.chmod(SECRET_KEY_PATH, 0o600)
    except Exception:
        pass
    return key
