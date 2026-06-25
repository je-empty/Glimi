"""첫 실행 setup wizard 라우터 — /setup (페이지) + /api/setup (적용)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import setup as setup_mod
from .. import templates

router = APIRouter()


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    # 이미 설정 완료면 위저드 숨김 — 홈으로.
    if setup_mod.is_configured():
        return RedirectResponse(url="/", status_code=303)
    return templates.env.TemplateResponse(request, "setup.html", {})


@router.post("/api/setup")
async def api_setup(request: Request):
    # 첫 실행에만 허용. 완료 후엔 잠금(누구나 admin 리셋 못 하게).
    if setup_mod.is_configured():
        return JSONResponse(status_code=403, content={"error": "이미 설정이 완료되었습니다."})
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "잘못된 요청 형식"})
    try:
        result = setup_mod.apply_setup(
            backend=payload.get("backend", ""),
            admin_password=payload.get("admin_password", ""),
            api_key=payload.get("api_key", ""),
            use_cli=bool(payload.get("use_cli", False)),
            tier=payload.get("tier", "standard"),
            monthly_cap_usd=payload.get("monthly_cap_usd", setup_mod.DEFAULT_MONTHLY_CAP_USD),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {"ok": True, **result}
