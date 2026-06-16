"""Dashboard FastAPI 라우터 — 로직은 src.platform.dashboard (api/actions) 에서 import.

HTML/CSS/JS 는 static + Jinja 로 분리됨 (scripts/web_dashboard.py 모노리스 해체 완료).
"""
import json as _json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import accounts
from ..auth import require_user
from ..dashboard import api as dash_api, actions as dash_actions


router = APIRouter()


def _full_path(req: Request) -> str:
    q = req.url.query
    return f"{req.url.path}?{q}" if q else req.url.path


def _ensure_community_access(req: Request, user: dict) -> None:
    cid = req.query_params.get("community")
    if cid:
        if not accounts.user_can_access(user, cid):
            raise HTTPException(403, "no access")
        # 삭제된 커뮤니티에 대한 stale 폴링 차단 — 디렉토리 없으면 하위 코드가 자동 생성해서
        # 빈 커뮤니티 부활시킴. 존재 안 하면 여기서 끊어냄.
        from src.community import COMMUNITIES_DIR
        if not (COMMUNITIES_DIR / cid).exists():
            raise HTTPException(404, f"community not found: {cid}")


# 한세나 (dev agent) 가시성 — 모든 커뮤니티에서 동일.
# server 는 항상 snapshot 에 포함 + dev_pending_count 같이 노출.
# 클라이언트 (dashboard.js) 가 supervisor view 토글 ON 일 때만 dev 카드/노드/배지 표시.
# admin 페이지 (/admin/dev-requests) 는 require_admin 으로 별도 보호.


def _json_endpoint(fn):
    async def _handler(request: Request, user: dict = Depends(require_user)):
        _ensure_community_access(request, user)
        try:
            data = fn(_full_path(request))
            cid = request.query_params.get("community") or (data.get("community_id") if isinstance(data, dict) else None)
            # community pending dev_request 카운트 — 헤더 배지용 (frontend 가 토글 기준 표시)
            if isinstance(data, dict) and cid and "dev_pending_count" not in data:
                try:
                    from src.core.dev_agent import count_pending_for_community
                    data["dev_pending_count"] = count_pending_for_community(cid)
                    data["dev_visible"] = True
                except Exception:
                    pass
            return JSONResponse(data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse({"error": str(e)}, status_code=500)
    return _handler


# ── GET JSON 엔드포인트 ───────────────────────
router.get("/api/snapshot")(_json_endpoint(dash_api.api_snapshot))
router.get("/api/logs")(_json_endpoint(dash_api.api_logs))
router.get("/api/agent_activity")(_json_endpoint(dash_api.api_agent_activity))
router.get("/api/agent")(_json_endpoint(dash_api.api_agent_detail))
router.get("/api/channel")(_json_endpoint(dash_api.api_channel_detail))
router.get("/api/health")(_json_endpoint(dash_api.api_health))
router.get("/api/dev")(_json_endpoint(dash_api.api_dev))
router.get("/api/usage")(_json_endpoint(dash_api.api_usage))
router.get("/api/i18n")(_json_endpoint(dash_api.api_i18n))
router.get("/api/achievements")(_json_endpoint(dash_api.api_achievements))
router.get("/api/achievement_detail")(_json_endpoint(dash_api.api_achievement_detail))


@router.get("/api/models")
async def models_endpoint(user: dict = Depends(require_user)):
    return dash_api.api_models()


@router.get("/api/elastic-memory")
async def elastic_memory_get(request: Request, user: dict = Depends(require_user)):
    """Elastic Memory — 현재 컨텍스트 설정 + 사양 + 권장값."""
    _ensure_community_access(request, user)
    cid = request.query_params.get("community")
    if not cid:
        return JSONResponse({"error": "missing community"}, status_code=400)
    from src.core import system_specs
    return JSONResponse(system_specs.elastic_memory_status(cid))


@router.post("/api/elastic-memory/set")
async def elastic_memory_set(request: Request, user: dict = Depends(require_user)):
    """컨텍스트(num_ctx) 변경 — community .env 에 저장. 다음 봇 (재)기동 시 적용."""
    body = await request.json()
    cid = body.get("community")
    if not cid:
        return JSONResponse({"error": "missing community"}, status_code=400)
    if not accounts.user_can_access(user, cid):
        raise HTTPException(403, "no access")
    from src.core import system_specs
    # num_ctx 직접 지정 또는 use_recommended 플래그
    if body.get("use_recommended"):
        target = system_specs.recommend_num_ctx()["num_ctx"]
    else:
        try:
            target = int(body.get("num_ctx"))
        except (TypeError, ValueError):
            return JSONResponse({"error": "invalid num_ctx"}, status_code=400)
    saved = system_specs.write_community_num_ctx(cid, target)
    return JSONResponse({"ok": True, **system_specs.elastic_memory_status(cid), "saved_num_ctx": saved})


@router.get("/logo")
async def serve_logo():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent.parent
    # SVG 우선 (벡터 — 파비콘/레티나 모두 선명), 없으면 구 PNG fallback
    logo_svg = root / "resources" / "Glimi-logo.svg"
    if logo_svg.exists():
        return Response(
            content=logo_svg.read_bytes(),
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    logo_path = root / "resources" / "Glimi-logo.png"
    if not logo_path.exists():
        return Response(status_code=404)
    return Response(
        content=logo_path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/sw.js")
async def serve_service_worker():
    """Serve the PWA service worker from the ROOT path so it may claim ``scope: /``.

    A service worker can only control a scope at or below its own URL's path. The
    file lives under ``/static/js/sw.js`` (StaticFiles), but a worker served from
    ``/static/js/`` could only control ``/static/js/*``. Serving it here at
    ``/sw.js`` with the ``Service-Worker-Allowed: /`` header lets it register with
    root scope (so it can cache navigations + the app shell across the whole app).
    No-store on the SW script itself so a new deploy's worker is always fetched
    fresh; the worker then versions ITS cache by the ``?v=`` query (asset_v).
    """
    from pathlib import Path
    sw_path = Path(__file__).resolve().parent.parent / "static" / "js" / "sw.js"
    if not sw_path.exists():
        return Response(status_code=404)
    return Response(
        content=sw_path.read_bytes(),
        media_type="text/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-store",
        },
    )


# ── POST mutations ────────────────────────────
_POST_MUTATIONS = {
    "/api/action/scan_discord": dash_actions.api_action_scan_discord,
    "/api/action/run_sync": dash_actions.api_action_run_sync,
    "/api/action/arrange_channels": dash_actions.api_action_arrange_channels,
    "/api/action/restore": dash_actions.api_action_restore,
    "/api/action/channel_clear": dash_actions.api_action_channel_clear,
    "/api/action/channel_delete": dash_actions.api_action_channel_delete,
    "/api/action/trash_message": dash_actions.api_action_trash_message,
    "/api/action/trash_list": dash_actions.api_action_trash_list,
    "/api/action/trash_restore": dash_actions.api_action_trash_restore,
    "/api/action/trash_empty": dash_actions.api_action_trash_empty,
    "/api/action/set_agent_model": dash_actions.api_action_set_agent_model,
}


@router.post("/api/action/{action_name:path}")
async def dispatch_action(action_name: str, request: Request, user: dict = Depends(require_user)):
    full = f"/api/action/{action_name}"
    fn = _POST_MUTATIONS.get(full)
    if fn is None:
        raise HTTPException(404, "unknown action")
    _ensure_community_access(request, user)

    body_bytes = await request.body()
    try:
        body = _json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        body = {}

    cid = request.query_params.get("community", "")
    # 대부분의 action 이 내부에서 asyncio.new_event_loop() 를 사용 (Discord client).
    # FastAPI async 핸들러에서 직접 호출하면 "loop already running" 충돌 →
    # 스레드풀에서 돌려야 함.
    #
    # **커뮤니티 컨텍스트 스위치 필수**: POST action 들은 global state
    # (env GLIMI_COMMUNITY, db.DB_PATH, profile cache, webhook cache) 에 의존.
    # 다른 커뮤니티의 GET 요청이 끼어들어서 active community 를 바꿔놓으면,
    # cid 가 test 여도 실제로는 demo DB/token 으로 sync 돌아가서 엉뚱한 서버를
    # 망침. with_community_nonblocking 이 maintenance pin 도 잡아서 스위치를
    # action 끝날 때까지 차단.
    from fastapi.concurrency import run_in_threadpool
    from ..dashboard.context import with_community_nonblocking
    full_path = _full_path(request)

    def _run_with_context():
        return with_community_nonblocking(full_path, lambda: fn(body, cid))

    try:
        result = await run_in_threadpool(_run_with_context)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse(result)
