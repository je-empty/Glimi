"""FastAPI 앱 엔트리 — 라우터 조립 + static 마운트 + supervisor 수명주기."""
import atexit
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import accounts, templates  # noqa: F401 — 서브모듈 초기화
from .db import init_db
from .routers import admin_dev, auth, communities, dashboard, pages
from .supervisor import supervisor

_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if not accounts.list_accounts():
        print("[platform] 계정 DB 비어있음 — bootstrap 실행")
        accounts.bootstrap()

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


app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(communities.router)
app.include_router(communities.avatar_router)
app.include_router(dashboard.router)
app.include_router(admin_dev.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "running_communities": supervisor.list_running()}


def _term_handler(signum, frame):
    supervisor.shutdown_all(timeout=5.0)
    sys.exit(0)


signal.signal(signal.SIGTERM, _term_handler)
atexit.register(lambda: supervisor.shutdown_all(timeout=3.0))
