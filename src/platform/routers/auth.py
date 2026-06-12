"""로그인/로그아웃 라우터."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import accounts, setup as setup_mod, templates
from ..config import SESSION_COOKIE_NAME, SESSION_MAX_AGE_SEC
from ..sessions import sign_session

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/", error: str | None = None):
    # 첫 실행이면 로그인 대신 setup wizard 로.
    if not setup_mod.is_configured():
        return RedirectResponse(url="/setup", status_code=303)
    return templates.env.TemplateResponse(
        request,
        "login.html",
        {"next": next, "error": error},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user = accounts.get_user(username)
    if not user or not accounts.verify_password(password, user["password_hash"]):
        # GET /login 으로 redirect 하면서 error 전달
        return RedirectResponse(
            url=f"/login?next={next}&error=invalid",
            status_code=303,
        )

    token = sign_session(user["id"])
    resp = RedirectResponse(url=next or "/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE_SEC,
        httponly=True,
        samesite="lax",
        secure=False,  # HTTPS 프로덕션 시 True
    )
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE_NAME)
    return resp
