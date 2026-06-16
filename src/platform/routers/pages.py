"""HTML 페이지 라우터 — 로그인 / 홈 (커뮤니티 리스트) / 커뮤니티 대시보드."""
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from src.community import list_communities

from .. import accounts, setup as setup_mod, templates
from ..auth import get_current_user, require_admin, require_user
from ..supervisor import supervisor

from .communities import _fetch_members, _visible_communities

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # 첫 실행이면 setup wizard 로.
    if not setup_mod.is_configured():
        return RedirectResponse(url="/setup", status_code=303)
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


@router.get("/community/{community_id}/chat", response_class=HTMLResponse)
async def community_chat(
    request: Request,
    community_id: str,
    user: dict = Depends(require_user),
):
    """웹 채팅 페이지 (Phase 1 — Outbox/Inbox seam + WS echo).
    /community/{community_id} 보다 먼저 등록되어야 함 (path 충돌 방지)."""
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access to this community")

    all_communities = list_communities()
    target = next((c for c in all_communities if c["id"] == community_id), None)
    if target is None:
        raise HTTPException(404, "community not found")

    # 채널/에이전트는 쿼리로 override 가능. 기본 = 오너↔mgr DM.
    agent_id = request.query_params.get("agent") or "mgr"
    channel = request.query_params.get("channel") or f"dm-{agent_id}"

    return templates.env.TemplateResponse(
        request,
        "chat.html",
        {
            "user": user,
            "community_id": community_id,
            "community_name": target.get("name") or community_id,
            "channel": channel,
            "agent_id": agent_id,
        },
    )


@router.get("/community/{community_id}", response_class=HTMLResponse)
async def community_dashboard(
    request: Request,
    community_id: str,
    user: dict = Depends(require_user),
):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access to this community")

    all_communities = list_communities()
    target = next((c for c in all_communities if c["id"] == community_id), None)
    if target is None:
        raise HTTPException(404, "community not found")

    # 커뮤니티 언어 — registry 에서 직접 읽음 (set_community 호출 X: 전역 캐시 오염 방지).
    import tomllib
    from src.community import REGISTRY_PATH
    _lang = "en"
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "rb") as f:
            _reg = tomllib.load(f)
        _lang = _reg.get("community", {}).get(community_id, {}).get("language", "en")

    return templates.env.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "user": user,
            "community_id": community_id,
            "community_name": target.get("name") or community_id,
            "community_description": target.get("description") or "",
            "language": _lang,
        },
    )


@router.get("/agent/{agent_id}", response_class=HTMLResponse)
async def agent_detail_page(
    request: Request,
    agent_id: str,
    community: str,
    user: dict = Depends(require_user),
):
    """에이전트 상세 전체 페이지 — 기존 모달을 풀 화면으로 확장.
    모달은 요약 카드 + "전체 보기" 버튼만, 실제 밀도 있는 정보는 여기."""
    if not accounts.user_can_access(user, community):
        raise HTTPException(403, "no access to this community")

    all_communities = list_communities()
    target = next((c for c in all_communities if c["id"] == community), None)
    if target is None:
        raise HTTPException(404, "community not found")

    # 커뮤니티 언어 — registry 에서 직접 읽음 (set_community 호출 X: 전역 캐시 오염 방지).
    import tomllib
    from src.community import REGISTRY_PATH
    _lang = "en"
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "rb") as f:
            _reg = tomllib.load(f)
        _lang = _reg.get("community", {}).get(community, {}).get("language", "en")

    return templates.env.TemplateResponse(
        request,
        "agent_detail.html",
        {
            "user": user,
            "agent_id": agent_id,
            "community_id": community,
            "community_name": target.get("name") or community,
            "language": _lang,
        },
    )


@router.get("/admin/dev-requests", response_class=HTMLResponse)
async def admin_dev_requests_page(
    request: Request,
    user: dict = Depends(require_admin),
):
    """글로벌 admin 페이지 — 모든 community 의 dev_requests 통합 검토 + Run."""
    return templates.env.TemplateResponse(
        request,
        "admin/dev_requests.html",
        {"user": user},
    )
