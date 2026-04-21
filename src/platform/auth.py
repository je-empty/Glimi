"""FastAPI 인증 의존성 — 요청에서 세션 쿠키 읽어 user 주입."""
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

from . import accounts
from .config import SESSION_COOKIE_NAME
from .sessions import verify_session


def get_current_user(request: Request) -> Optional[dict]:
    """로그인 되어 있으면 user dict, 아니면 None. 라우터에서 Depends 로 사용."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session(token) if token else None
    if not user_id:
        return None
    return accounts.get_user_by_id(user_id)


def require_user(request: Request) -> dict:
    """로그인 필수 엔드포인트. 없으면 /login 리다이렉트 (HTML) 또는 401 (API)."""
    user = get_current_user(request)
    if user:
        return user

    # API 요청이면 JSON 401, HTML 요청이면 /login 리다이렉트
    accept = request.headers.get("accept", "")
    if "application/json" in accept or request.url.path.startswith("/api/"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login_required")
    raise HTTPException(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"/login?next={request.url.path}"},
    )


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    return user


def require_community_access(request: Request, community_id: str) -> dict:
    user = require_user(request)
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no_community_access")
    return user
