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
    if cid and not accounts.user_can_access(user, cid):
        raise HTTPException(403, "no access")


def _json_endpoint(fn):
    async def _handler(request: Request, user: dict = Depends(require_user)):
        _ensure_community_access(request, user)
        try:
            data = fn(_full_path(request))
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


@router.get("/api/models")
async def models_endpoint(user: dict = Depends(require_user)):
    return dash_api.api_models()


@router.get("/logo")
async def serve_logo():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent.parent
    logo_path = root / "resources" / "Glimi-logo.png"
    if not logo_path.exists():
        return Response(status_code=404)
    return Response(
        content=logo_path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
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
    from fastapi.concurrency import run_in_threadpool
    try:
        result = await run_in_threadpool(fn, body, cid)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse(result)
