"""FastAPI 앱 엔트리 — 라우터 조립 + static 마운트 + supervisor 수명주기."""
import atexit
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import os

from . import accounts, setup as setup_mod, templates  # noqa: F401 — 서브모듈 초기화
from .db import init_db
from .routers import admin_dev, auth, chat, communities, dashboard, pages, setup as setup_router
from .supervisor import supervisor

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not accounts.list_accounts():
        # 비대화형(도커/CI)에서 GLIMI_ADMIN_PASSWORD 를 줬으면 자동 부트스트랩.
        # 아니면 웹 setup wizard(/setup)가 처리하므로 여기선 건너뛴다.
        if os.environ.get("GLIMI_ADMIN_PASSWORD", "").strip():
            print("[platform] 계정 DB 비어있음 — GLIMI_ADMIN_PASSWORD 로 bootstrap")
            accounts.bootstrap()
        else:
            print("[platform] 첫 실행 — http://<host>/setup 에서 초기 설정")

    # 첫 실행 1회: demo(목업) 커뮤니티 자동 시딩 + registry 등록.
    # 마커로 가드 → 사용자가 나중에 demo 를 지워도 재시드되지 않음.
    from .config import DATA_DIR
    _demo_marker = DATA_DIR / ".demo_seeded"
    if not _demo_marker.exists():
        try:
            from .demo_seed import ensure_demo_seeded
            ensure_demo_seeded()
        except Exception as e:  # startup 보호 — demo 실패는 무시
            print(f"[platform] demo seed skipped: {e}")
        finally:
            try:
                _demo_marker.write_text("ok\n", encoding="utf-8")
            except Exception:
                pass

    # demo-live (초대전용 실모델 시연) — 공개 demo 를 채팅 가능 presenter 로 복제.
    # 마커와 무관하게 매 기동 보장(기존 배포에도 생기도록) — idempotent: 이미 있으면
    # .env/registry 만 갱신, demo 가 없는 인스턴스(예: 오너 실사용)에선 no-op.
    try:
        from .demo_seed import ensure_demo_live_seeded
        ensure_demo_live_seeded()
    except Exception as e:  # startup 보호
        print(f"[platform] demo-live seed skipped: {e}")

    # 구 web_dashboard 의 startup community 개념: 없으면 default 리졸브
    from src import community as _comm
    from .dashboard.context import set_startup_community
    try:
        set_startup_community(_comm.get_community_id())
    except Exception:
        pass

    print("[platform] ready")
    yield
    print("[platform] shutdown — 봇 subprocess 정리 중")
    supervisor.shutdown_all()


app = FastAPI(title="Glimi Platform", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.exception_handler(Exception)
async def _unhandled(request, exc):
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"error": str(exc)})


app.include_router(setup_router.router)
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(communities.router)
app.include_router(communities.avatar_router)
app.include_router(dashboard.router)
app.include_router(admin_dev.router)
app.include_router(chat.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "running_communities": supervisor.list_running()}


def _term_handler(signum, frame):
    print(f"\n[platform] *** SIGTERM 수신 (signum={signum}) — 봇 정리 중 ***", flush=True)
    supervisor.shutdown_all(timeout=5.0)
    sys.exit(0)


# Windows 에서는 SIGTERM 이 의도치 않게 트리거되는 케이스 있어 (자식 process 의 console
# event 전파). SIGTERM handler 등록은 POSIX 만. Windows 는 atexit 으로 충분 — 사용자가
# Ctrl+C 로 끄면 KeyboardInterrupt 가 uvicorn 까지 자연스럽게 전파.
if sys.platform != "win32":
    signal.signal(signal.SIGTERM, _term_handler)

atexit.register(lambda: supervisor.shutdown_all(timeout=3.0))
