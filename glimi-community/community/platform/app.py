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
from .routers import admin_dev, auth, chat, communities, dashboard, pages, setup as setup_router, visits
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

    # 구 web_dashboard 의 startup community 개념: 없으면 default 리졸브
    from community import community as _comm
    from .dashboard.context import set_startup_community
    try:
        set_startup_community(_comm.get_community_id())
    except Exception:
        pass

    # Web 자율 드라이버 — 각 활성(read_only=False) 커뮤니티마다 WebRuntime 기동.
    # supervisor 가 WebRuntime 을 소유: boot_community + 풀 등록 + 유나 PROACTIVE 첫 인사 +
    # tick 루프를 담당 (구 discord on_ready / @tasks.loop 대체). read_only(데모)는 자율 구동 안 함.
    try:
        for c in _comm.list_communities():
            cid = c.get("id")
            if not cid or c.get("read_only"):
                continue
            try:
                await supervisor.start_async(cid)
            except Exception as e:
                print(f"[platform] WebRuntime({cid}) 기동 실패: {e}")
    except Exception as e:
        print(f"[platform] WebRuntime 일괄 기동 스킵: {e}")

    print("[platform] ready")
    yield
    print("[platform] shutdown — WebRuntime 정리 중")
    await supervisor.shutdown_all_async()


app = FastAPI(title="Glimi Platform", lifespan=lifespan)

# 정적 랜딩(다른 오리진)에서 오는 방문 비콘만 위한 opt-in CORS. 비우면(기본) same-origin
# 전용 — 즉 커뮤니티가 직접 서빙하는 페이지만 추적. 배포 시 GLIMI_CORS_ORIGINS="https://glimi.example"
# 로 랜딩 오리진을 허용. allow_credentials=False 라 admin 쿠키 엔드포인트는 교차오리진 노출 안 됨.
_cors_origins = [o.strip() for o in (os.environ.get("GLIMI_CORS_ORIGINS") or "").split(",") if o.strip()]
if _cors_origins:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["content-type"],
        allow_credentials=False,
    )

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
app.include_router(visits.router)
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
