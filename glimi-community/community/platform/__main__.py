"""`python -m community.platform` → uvicorn 으로 플랫폼 구동.

옵션:
  --host HOST (default: 0.0.0.0)
  --port PORT (default: 8765)
  --reload    개발용 reload
"""
import argparse
import logging
import os

import uvicorn

from .config import DEFAULT_HOST, DEFAULT_PORT


# Polling 엔드포인트 — 대시보드가 주기적으로 GET/POST. uvicorn.access INFO 로그 도배 차단.
# 기능은 그대로 동작, 출력만 숨김. POST run_sync 같은 진짜 액션은 유지됨.
_NOISY_PATH_SUBSTRINGS = (
    "/api/health",
    "/api/dev?",
    "/api/logs?",
    "/api/usage?",
    "/api/snapshot?",
    "/api/achievements?",
    "/api/action/trash_list",
    "/api/communities ",        # GET /api/communities (목록)
    "/api/communities?",
    "/status HTTP",             # GET /api/communities/{cid}/status
    "/api/tutorial_progress",   # polling 가능성 있는 다른 엔드포인트
    "/favicon.ico",             # 브라우저 자동 요청 — 404 무시
    "/api/avatar?",             # 아바타 이미지 로드 (페이지 마다 다수 요청)
    "/api/i18n?",               # 언어 리소스 로드
    "/api/agent_activity?",     # 에이전트 thinking/speaking 상태 polling
    "/api/agent?",              # 에이전트 메타 polling
)


class _AccessLogFilter(logging.Filter):
    """uvicorn.access 로그에서 polling 엔드포인트만 drop. 다른 요청은 그대로."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for path in _NOISY_PATH_SUBSTRINGS:
            if path in msg:
                return False
        return True


def _install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    logger.addFilter(_AccessLogFilter())


def main() -> None:
    ap = argparse.ArgumentParser(prog="community.platform")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    _install_access_log_filter()

    # WebSocket keepalive — env-gated so a slow synchronous backend (claude_cli blocks
    # the loop for 30-90s) doesn't get its chat WS dropped (1011 keepalive timeout).
    # Defaults unchanged (20/20) for prod; the E2E harness sets GLIMI_WS_PING_INTERVAL=0
    # to disable pings entirely so a long drive survives. "0"/"none"/"off" → None.
    def _ws_ping(name: str, default: float):
        v = os.environ.get(name)
        if v is None:
            return default
        v = v.strip().lower()
        if v in ("", "0", "none", "off"):
            return None
        try:
            return float(v)
        except ValueError:
            return default

    uvicorn.run(
        "community.platform.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        ws_ping_interval=_ws_ping("GLIMI_WS_PING_INTERVAL", 20.0),
        ws_ping_timeout=_ws_ping("GLIMI_WS_PING_TIMEOUT", 20.0),
    )


if __name__ == "__main__":
    main()
