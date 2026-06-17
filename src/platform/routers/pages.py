"""HTML 페이지 라우터 — 로그인 / 홈 (커뮤니티 리스트) / 커뮤니티 대시보드."""
import os

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from src.community import is_read_only, list_communities

from .. import accounts, setup as setup_mod, templates
from ..auth import get_current_user, public_readonly_user, require_admin, require_user
from ..supervisor import supervisor

from .communities import _fetch_members, _visible_communities

router = APIRouter()

# Public showcase front (optional, deployment-driven). When the platform is
# reached on GLIMI_FRONT_HOST, the root serves a no-login landing that links to
# the live demos; the apps themselves live on other hosts (e.g. community.* /
# workspace.*). Default unset → no landing, the OSS default behavior is unchanged.
_FRONT_HOST = os.environ.get("GLIMI_FRONT_HOST", "").strip().lower()
_WORKSPACE_URL = os.environ.get("GLIMI_WORKSPACE_URL", "").strip()
# Community demo lives on its own host (community.*) in deployment; the landing
# links there directly so the showcase front never points at itself. Unset →
# fall back to the same-host route (/community/demo).
_COMMUNITY_URL = os.environ.get("GLIMI_COMMUNITY_URL", "").strip()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # 첫 실행이면 setup wizard 로.
    if not setup_mod.is_configured():
        return RedirectResponse(url="/setup", status_code=303)
    # 공개 쇼케이스 프론트: GLIMI_FRONT_HOST 로 들어오면 로그인 없이 랜딩(데모 링크).
    # 실제 앱은 다른 호스트(community.* / workspace.*)에서 동작.
    if _FRONT_HOST:
        host = (request.headers.get("host") or "").split(":")[0].strip().lower()
        if host == _FRONT_HOST:
            # Language picker: ?lang=en → English demo (demo-en); default ko.
            lang = "en" if request.query_params.get("lang") == "en" else "ko"
            community_url = _COMMUNITY_URL or "/community/demo"
            community_url_en = community_url.replace("/community/demo", "/community/demo-en")
            return templates.env.TemplateResponse(
                request, "landing.html",
                {"workspace_url": _WORKSPACE_URL,
                 "community_url": community_url,
                 "community_url_en": community_url_en,
                 "lang": lang})
    user = get_current_user(request)
    if not user:
        # 로그아웃 방문자: read-only(데모) 둘러보기로 보냄 (커뮤니티 리스트는 노출 X).
        # demo 가 존재 + read_only 일 때만. 아니면 기존대로 /login.
        if any(c["id"] == "demo" for c in list_communities()) and is_read_only("demo"):
            return RedirectResponse(url="/community/demo", status_code=303)
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
):
    """웹 채팅 페이지 (Phase 1 — Outbox/Inbox seam + WS echo).
    /community/{community_id} 보다 먼저 등록되어야 함 (path 충돌 방지).

    공개 둘러보기: read-only(데모) 커뮤니티는 익명도 열람 가능 (read 전용).
    read_only 를 템플릿에 전달 → 컴포저 비활성 + 배너 (전원 동일)."""
    user = public_readonly_user(request, community_id)

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
            # read-only(데모 목업) → 컴포저 비활성 + 배너 (look-only 쇼케이스)
            "read_only": bool(target.get("read_only")),
        },
    )


@router.get("/community/{community_id}", response_class=HTMLResponse)
async def community_dashboard(
    request: Request,
    community_id: str,
):
    # 공개 둘러보기: read-only(데모)는 익명 열람 가능 (read 전용). read_only 를
    # 템플릿에 전달 → 임베드 채팅 컴포저 비활성 + 배너 (전원 동일).
    user = public_readonly_user(request, community_id)

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
            # read-only(데모 목업) → 임베드 채팅 컴포저 비활성 + 배너
            "read_only": bool(target.get("read_only")),
            # 임베드된 채팅 탭 기본 채널/에이전트 — 오너↔mgr DM (standalone /chat 기본과 동일).
            "chat_agent": "mgr",
            "chat_channel": "dm-mgr",
        },
    )


@router.get("/agent/{agent_id}", response_class=HTMLResponse)
async def agent_detail_page(
    request: Request,
    agent_id: str,
    community: str,
):
    """에이전트 상세 전체 페이지 — 기존 모달을 풀 화면으로 확장.
    모달은 요약 카드 + "전체 보기" 버튼만, 실제 밀도 있는 정보는 여기.

    READ 전용 → public_readonly_user 게이트: 로그인 멤버는 그대로, 익명은
    read-only(데모) 커뮤니티에서만 둘러보기 허용 (대시보드 anon 뷰와 동일 규약)."""
    user = public_readonly_user(request, community)  # anon ⟺ is_read_only(community)

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
