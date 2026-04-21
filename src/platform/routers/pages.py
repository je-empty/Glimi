"""HTML 페이지 라우터 — 로그인 / 홈 (커뮤니티 리스트) / 커뮤니티 대시보드."""
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from src.community import list_communities

from .. import accounts, templates
from ..auth import get_current_user, require_user
from ..supervisor import supervisor

from .communities import _fetch_members, _visible_communities

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    visible = _visible_communities(user)
    running = set(supervisor.list_running())
    for c in visible:
        c["running"] = c["id"] in running
        c["members"] = _fetch_members(c["id"])
        c["member_count"] = len(c["members"])

    return templates.env.TemplateResponse(
        request,
        "home.html",
        {"user": user, "communities": visible},
    )


@router.get("/community/new", response_class=HTMLResponse)
async def new_community(
    request: Request,
    user: dict = Depends(require_user),
):
    """새 커뮤니티 생성 위저드 — 4 스텝 페이지.
    /community/{community_id} 보다 먼저 등록되어야 함 (path param 충돌 방지)."""
    return templates.env.TemplateResponse(
        request,
        "new_community.html",
        {"user": user},
    )


@router.get("/community/{community_id}", response_class=HTMLResponse)
async def community_dashboard(
    request: Request,
    community_id: str,
    user: dict = Depends(require_user),
):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access to this community")

    all_ids = {c["id"] for c in list_communities()}
    if community_id not in all_ids:
        raise HTTPException(404, "community not found")

    return templates.env.TemplateResponse(
        request,
        "dashboard/index.html",
        {"user": user, "community_id": community_id},
    )
