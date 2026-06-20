"""Dashboard FastAPI 라우터 — 로직은 community.platform.dashboard (api/actions) 에서 import.

HTML/CSS/JS 는 static + Jinja 로 분리됨 (scripts/web_dashboard.py 모노리스 해체 완료).
"""
import json as _json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import accounts
from ..auth import public_readonly_user, require_user
from ..dashboard import api as dash_api, actions as dash_actions


router = APIRouter()


def _full_path(req: Request) -> str:
    q = req.url.query
    return f"{req.url.path}?{q}" if q else req.url.path


def _ensure_community_access(req: Request, user: dict, public_readonly: bool = False) -> None:
    """커뮤니티 접근 검사. public_readonly=True 인 GET read 엔드포인트는 익명도
    read-only(데모) 커뮤니티에 한해 허용 — predicate 는 auth.public_readonly_user
    (단일 진실의 원천) 가 강제. 그 외(write·비-read_only)는 전부 require_user 유지.

    공개 허용 엔드포인트도 항상 query 의 specific community 에 바인딩하고, 익명은
    절대 비-read_only 커뮤니티에 닿지 못한다 (predicate 가 401/redirect 발생)."""
    cid = req.query_params.get("community")
    if not cid:
        return
    if public_readonly:
        # predicate: anon 허용 ⟺ is_read_only(cid). 로그인 비멤버는 403.
        # 익명 read-only 면 None 반환(통과), 아니면 require_user 와 동일 실패.
        public_readonly_user(req, cid)
    elif not accounts.user_can_access(user, cid):
        raise HTTPException(403, "no access")
    # 삭제된 커뮤니티에 대한 stale 폴링 차단 — 디렉토리 없으면 하위 코드가 자동 생성해서
    # 빈 커뮤니티 부활시킴. 존재 안 하면 여기서 끊어냄.
    from community.community import COMMUNITIES_DIR
    if not (COMMUNITIES_DIR / cid).exists():
        raise HTTPException(404, f"community not found: {cid}")


# 한세나 (dev agent) 가시성 — 모든 커뮤니티에서 동일.
# server 는 항상 snapshot 에 포함 + dev_pending_count 같이 노출.
# 클라이언트 (dashboard.js) 가 supervisor view 토글 ON 일 때만 dev 카드/노드/배지 표시.
# admin 페이지 (/admin/dev-requests) 는 require_admin 으로 별도 보호.


def _json_endpoint(fn, public_readonly: bool = False):
    """GET JSON 엔드포인트 팩토리.

    public_readonly=True 면 익명도 read-only(데모) 커뮤니티에 한해 허용한다
    (데모 대시보드가 렌더되도록). 이때 인증 강제는 _ensure_community_access 의
    public_readonly_user predicate 가 담당하므로, 라우트 레벨 Depends(require_user)
    는 떼고(익명 통과) 안에서 predicate 로 게이트한다. 기본(False)은 종전대로
    require_user 의존성으로 전 요청을 로그인 게이트한다."""
    if public_readonly:
        from ..auth import get_current_user
        async def _handler(request: Request, user: dict = Depends(get_current_user)):
            _ensure_community_access(request, user, public_readonly=True)
            return await _emit(fn, request)
        return _handler

    async def _handler(request: Request, user: dict = Depends(require_user)):
        _ensure_community_access(request, user)
        return await _emit(fn, request)
    return _handler


async def _emit(fn, request: Request) -> JSONResponse:
    """공통 본문 — community 컨텍스트 검사 통과 후 핸들러 실행 + dev 배지 주입."""
    try:
        data = fn(_full_path(request))
        cid = request.query_params.get("community") or (data.get("community_id") if isinstance(data, dict) else None)
        # community pending dev_request 카운트 — 헤더 배지용 (frontend 가 토글 기준 표시)
        if isinstance(data, dict) and cid and "dev_pending_count" not in data:
            try:
                from community.core.dev_agent import count_pending_for_community
                data["dev_pending_count"] = count_pending_for_community(cid)
                data["dev_visible"] = True
            except Exception:
                pass
        return JSONResponse(data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


# ── GET JSON 엔드포인트 ───────────────────────
# public_readonly=True = 익명도 read-only(데모) 커뮤니티에 한해 허용 (데모
# 대시보드가 렌더되는 데 필요한 read 들). 그 외(logs/agent_activity/dev/
# achievements)는 require_user 유지 — 데모 대시보드는 j() 가 null 을 관용하므로
# 이것들이 401 이어도 깨지지 않는다 (불필요 노출 회피). 익명은 어떤 경우에도
# 비-read_only 커뮤니티에 닿지 못한다 (predicate 가 401/redirect).
_PUBLIC_READ = dict(public_readonly=True)
router.get("/api/snapshot")(_json_endpoint(dash_api.api_snapshot, **_PUBLIC_READ))
router.get("/api/logs")(_json_endpoint(dash_api.api_logs, **_PUBLIC_READ))
router.get("/api/agent_activity")(_json_endpoint(dash_api.api_agent_activity, **_PUBLIC_READ))
router.get("/api/agent")(_json_endpoint(dash_api.api_agent_detail, **_PUBLIC_READ))
router.get("/api/channel")(_json_endpoint(dash_api.api_channel_detail, **_PUBLIC_READ))
router.get("/api/health")(_json_endpoint(dash_api.api_health, **_PUBLIC_READ))
router.get("/api/dev")(_json_endpoint(dash_api.api_dev))  # admin (dev-requests) — owner only
router.get("/api/usage")(_json_endpoint(dash_api.api_usage, **_PUBLIC_READ))
router.get("/api/tool_timeline")(_json_endpoint(dash_api.api_tool_timeline, **_PUBLIC_READ))
router.get("/api/i18n")(_json_endpoint(dash_api.api_i18n, **_PUBLIC_READ))
# achievements/logs/agent_activity are public_readonly too: on a read_only demo the
# anon viewer should see the seeded Achievements/Logs tabs (richer demo + no 401
# console noise). public_readonly_user still bars anon from any non-read_only community.
router.get("/api/achievements")(_json_endpoint(dash_api.api_achievements, **_PUBLIC_READ))
router.get("/api/achievement_detail")(_json_endpoint(dash_api.api_achievement_detail, **_PUBLIC_READ))


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
    from community.core import system_specs
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
    from community.core import system_specs
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
