"""HTML 페이지 라우터 — 로그인 / 홈 (커뮤니티 리스트) / 커뮤니티 대시보드."""
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from src.community import is_read_only, list_communities

from .. import accounts, setup as setup_mod, templates
from ..auth import get_current_user, public_readonly_user, require_admin, require_user
from ..supervisor import supervisor

from .communities import _fetch_members, _visible_communities

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # 첫 실행이면 setup wizard 로.
    if not setup_mod.is_configured():
        return RedirectResponse(url="/setup", status_code=303)
    # 이 앱은 커뮤니티 전용 — 별도 랜딩 페이지는 없다.
    user = get_current_user(request)
    if not user:
        # 로그아웃 방문자: 공개(read-only 데모) 커뮤니티를 SHARED `_demo_list.html` 로
        # 보여준다 (워크스페이스 홈과 똑같은 목록 페이지). 언어(?lang)에 맞는 데모 하나만
        # (ko→내 커뮤니티, en→Your Community). 공개 데모가 없으면 /login.
        public = [c for c in list_communities() if c.get("read_only")]
        if not public:
            return RedirectResponse(url="/login", status_code=303)
        lang = (request.query_params.get("lang") or "ko").lower()
        if lang not in ("ko", "en"):
            lang = "ko"
        EN = (lang == "en")
        matched = [c for c in public if (c.get("language") or "ko").lower() == lang]
        shown = matched or public  # 언어 매칭 없으면 전체로 폴백
        items = []
        for c in shown:
            n = len(_fetch_members(c["id"]))
            metas = ([f"{n} friends"] if EN else [f"친구 {n}명"])
            items.append({
                "href": f"/community/{c['id']}",
                "title": c.get("name") or c["id"],
                "desc": c.get("description") or "",
                "is_demo": True,
                "metas": metas,
            })
        ctx = {
            "request": request, "lang": lang,
            "brand": "Glimi Community",
            "brand_sub": ("AI friends who live alongside each other" if EN
                          else "서로 곁에서 살아가는 AI 친구들"),
            "lede": ("Friends who talk to each other, remember, and grow closer. "
                     "Browse the demo below — no login." if EN
                     else "서로 대화하고, 기억하고, 관계를 쌓아가는 친구들. 아래 데모를 둘러보세요. 로그인 없이."),
            "items": items,
            "create": None,
        }
        return templates.env.TemplateResponse(request, "_demo_list.html", ctx)

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
            # 정본 셸(dashboard/_core.html) 파라미터: 커뮤니티는 풀 chrome + 전 caps.
            # api_base="" → dashboard.js 가 절대 /api/* + ?community= 로 라우팅 (data-api-base
            # 없음). caps_json 미전달 → CAPS=null → 모든 탭 노출.
            "community_chrome": True,
            "static_base": "/static",
            "api_base": "",
            "active_tab": "chat",
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
            # Canonical template params (shared with Workspace). Community uses absolute
            # /api/* + ?community= → api_base="" ; interactive (model switch) on.
            "api_base": "",
            "back_url": f"/community/{community}",
            "interactive": True,
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
