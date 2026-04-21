"""구 `scripts/web_dashboard.py` 를 importlib 로 재사용 → 동일 포트에서 모든 대시보드
엔드포인트 서빙.

단일 포트 유지를 위해 subprocess/프록시 대신 **같은 프로세스** 에서 직접 import.
web_dashboard 의 `api_*` 함수들은 이미 (path_string → dict) 형태라 FastAPI adapter 가 얕음.
"""
import importlib.util
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .. import accounts
from ..auth import require_user

ROOT = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_glimi_dashboard_legacy",
    str(ROOT / "scripts" / "web_dashboard.py"),
)
_dash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dash)


router = APIRouter()


def _full_path(req: Request) -> str:
    q = req.url.query
    return f"{req.url.path}?{q}" if q else req.url.path


def _ensure_community_access(req: Request, user: dict) -> None:
    cid = req.query_params.get("community")
    if cid and not accounts.user_can_access(user, cid):
        raise HTTPException(403, "no access")


def _json_endpoint(fn):
    """단순히 path → dict 를 반환하는 legacy api_* 래퍼."""
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


# ── GET JSON 엔드포인트 전부 매핑 ───────────────────────
router.get("/api/snapshot")(_json_endpoint(_dash.api_snapshot))
router.get("/api/logs")(_json_endpoint(_dash.api_logs))
router.get("/api/agent_activity")(_json_endpoint(_dash.api_agent_activity))
router.get("/api/agent")(_json_endpoint(_dash.api_agent_detail))
router.get("/api/channel")(_json_endpoint(_dash.api_channel_detail))
router.get("/api/health")(_json_endpoint(_dash.api_health))
router.get("/api/dev")(_json_endpoint(_dash.api_dev))
router.get("/api/usage")(_json_endpoint(_dash.api_usage))
router.get("/api/i18n")(_json_endpoint(_dash.api_i18n))
router.get("/api/achievements")(_json_endpoint(_dash.api_achievements))


@router.get("/api/models")
async def api_models(user: dict = Depends(require_user)):
    try:
        from src.core.runtime import AVAILABLE_MODELS
        return {"items": AVAILABLE_MODELS}
    except Exception as e:
        return {"error": str(e), "items": []}


@router.get("/logo")
async def serve_logo():
    logo_path = ROOT / "resources" / "Glimi-logo.png"
    if not logo_path.exists():
        return Response(status_code=404)
    return Response(
        content=logo_path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── POST mutations — fake handler 로 legacy do_POST 재사용 ───
import io
import json as _json


class _FakeHandler:
    """legacy web_dashboard.Handler 호환 최소 shim.
    `_send` / `send_response` / `send_header` / `end_headers` / `wfile.write` 만 쓰면 충분.
    """
    def __init__(self, path: str, headers: dict, body: bytes):
        self.path = path
        self.headers = headers
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self._status = 200
        self._headers = {}

    def send_response(self, code):
        self._status = code

    def send_header(self, k, v):
        self._headers[k] = str(v)

    def end_headers(self):
        pass

    def _send(self, status, body, ct):
        self._status = status
        self._headers["Content-Type"] = ct
        self.wfile.write(body)

    def _json(self, data):
        body = _json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")


# start/stop/restart 는 플랫폼 supervisor 가 담당 → legacy 의 그 3개는 뺌
_POST_MUTATIONS = {
    "/api/action/scan_discord": _dash.api_action_scan_discord,
    "/api/action/run_sync": _dash.api_action_run_sync,
    "/api/action/arrange_channels": _dash.api_action_arrange_channels,
    "/api/action/restore": _dash.api_action_restore,
    "/api/action/channel_clear": _dash.api_action_channel_clear,
    "/api/action/channel_delete": _dash.api_action_channel_delete,
    "/api/action/trash_message": _dash.api_action_trash_message,
    "/api/action/trash_list": _dash.api_action_trash_list,
    "/api/action/trash_restore": _dash.api_action_trash_restore,
    "/api/action/trash_empty": _dash.api_action_trash_empty,
    "/api/action/set_agent_model": _dash.api_action_set_agent_model,
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
    result = fn(body, cid)
    return JSONResponse(result)
