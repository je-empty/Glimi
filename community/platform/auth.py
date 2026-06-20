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


def public_readonly_user(request: Request, community_id: str) -> Optional[dict]:
    """공개 둘러보기(read-only 데모) 게이트 — READ 전용 라우트에서만 사용.

    단일 진실의 원천(predicate): **anon 허용 ⟺ is_read_only(community_id)**.
    항상 특정 target community 에 바인딩한다 (요청별 community 고정과 결합).

      - 로그인 유저: 해당 커뮤니티 접근 권한 있으면 user 반환, 없으면
        require_user 와 동일한 실패(비멤버 → 403 그대로). 로그인 비멤버는
        read-only 여도 막지 않고 자기 권한대로 처리 → 일반 멤버 게이트와 동일.
      - 익명(user None): 커뮤니티가 read_only 면 None(익명 둘러보기 허용),
        아니면 require_user 와 똑같은 실패(API 401 / HTML 307 redirect) 발생.

    READ 전용. 어떤 write/mutation 라우트에도 붙이지 말 것."""
    user = get_current_user(request)
    if user:
        if accounts.user_can_access(user, community_id):
            return user
        # 로그인했지만 비멤버 → read-only 여도 일반 멤버 게이트와 동일하게 403.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no_community_access")

    # 익명: read-only(데모)면 둘러보기 허용, 아니면 require_user 와 동일 실패.
    from community.community import is_read_only
    if is_read_only(community_id):
        return None
    return require_user(request)  # raises 401(API) / 307 redirect(HTML)


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
