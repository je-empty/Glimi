"""FastAPI 앱 엔트리 — 라우터 조립 + supervisor 수명주기."""
import atexit
import signal
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import accounts, templates  # noqa: F401 — 서브모듈 초기화
from .db import init_db
from .routers import auth, communities, dashboard, pages
from .supervisor import supervisor


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 최초 부팅 시 계정 없으면 bootstrap (admin/1234 + test/1234)
    if not accounts.list_accounts():
        print("[platform] 계정 DB 비어있음 — bootstrap 실행")
        accounts.bootstrap()

    print("[platform] ready")
    yield
    # 종료 시 모든 커뮤니티 봇 정리
    print("[platform] shutdown — 봇 subprocess 정리 중")
    supervisor.shutdown_all()


app = FastAPI(title="Glimi Platform", lifespan=lifespan)


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


@app.get("/healthz")
async def healthz():
    return {"ok": True, "running_communities": supervisor.list_running()}


# SIGTERM 처리 (uvicorn 외부 kill 시에도 봇 정리되게)
def _term_handler(signum, frame):
    supervisor.shutdown_all(timeout=5.0)
    sys.exit(0)


signal.signal(signal.SIGTERM, _term_handler)
atexit.register(lambda: supervisor.shutdown_all(timeout=3.0))
