"""`python -m src.platform` → uvicorn 으로 플랫폼 구동.

옵션:
  --host HOST (default: 0.0.0.0)
  --port PORT (default: 8765)
  --reload    개발용 reload
"""
import argparse

import uvicorn

from .config import DEFAULT_HOST, DEFAULT_PORT


def main() -> None:
    ap = argparse.ArgumentParser(prog="src.platform")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    uvicorn.run(
        "src.platform.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
