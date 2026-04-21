"""커뮤니티 CRUD + 봇 start/stop API."""
import hashlib
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.community import (
    COMMUNITIES_DIR,
    init_community,
    list_communities,
)

from .. import accounts
from ..auth import require_user
from ..community_ctx import run_in_community
from ..supervisor import supervisor

router = APIRouter(prefix="/api/communities")


class CreateCommunityIn(BaseModel):
    id: str
    language: str = "en"
    grant_to_user: str | None = None


def _visible_communities(user: dict) -> list[dict]:
    all_communities = list_communities()
    if user.get("role") == "admin":
        return all_communities
    allowed = set(accounts.list_communities_for_user(user["id"]))
    return [c for c in all_communities if c["id"] in allowed]


def _fetch_members(community_id: str, limit: int = 8) -> list[dict]:
    """community 의 에이전트 목록을 [{id, name, type, avatar_url}] 형태로 반환.
    avatar_url 은 /api/avatar?community=X&id=Y 로 프론트가 직접 로드.
    """
    if not (COMMUNITIES_DIR / community_id / "community.db").exists():
        return []

    def _query():
        from src.db import list_agents
        agents = list_agents()
        # persona 가장 먼저, 그 뒤 mgr/creator
        type_order = {"persona": 0, "mgr": 1, "creator": 2}
        agents.sort(key=lambda a: (type_order.get(a.get("type", ""), 9), a.get("created_at", "")))
        out = []
        for a in agents[:limit]:
            out.append({
                "id": a["id"],
                "name": a.get("name") or a["id"],
                "type": a.get("type", ""),
                "avatar_url": f"/api/avatar?community={community_id}&id={a['id']}",
            })
        return out

    try:
        return run_in_community(community_id, _query)
    except Exception:
        return []


@router.get("")
async def list_my_communities(user: dict = Depends(require_user)):
    running = set(supervisor.list_running())
    visible = _visible_communities(user)
    for c in visible:
        c["running"] = c["id"] in running
        c["members"] = _fetch_members(c["id"])
        c["member_count"] = len(c["members"])
    # 정렬: 실행 중 먼저 → default → 알파벳
    visible.sort(key=lambda c: (
        0 if c.get("running") else 1,
        0 if c.get("is_default") else 1,
        c.get("id", ""),
    ))
    return visible


@router.post("")
async def create(data: CreateCommunityIn, user: dict = Depends(require_user)):
    if any(c["id"] == data.id for c in list_communities()):
        raise HTTPException(400, "already exists")
    if not data.id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "id must be alphanumeric with -/_")

    init_community(data.id)
    accounts.grant_community(user["id"], data.id)
    if data.grant_to_user and user.get("role") == "admin":
        target = accounts.get_user(data.grant_to_user)
        if target:
            accounts.grant_community(target["id"], data.id)
    return {"ok": True, "id": data.id}


@router.delete("/{community_id}")
async def delete(community_id: str, user: dict = Depends(require_user)):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    if supervisor.status(community_id).get("running"):
        supervisor.stop(community_id)

    cdir = COMMUNITIES_DIR / community_id
    if cdir.exists():
        shutil.rmtree(cdir)

    from src.community import REGISTRY_PATH
    if REGISTRY_PATH.exists():
        content = REGISTRY_PATH.read_text()
        import re
        pattern = re.compile(
            rf'\n?\[community\.{re.escape(community_id)}\][^\[]*',
            re.MULTILINE,
        )
        REGISTRY_PATH.write_text(pattern.sub("", content))
    return {"ok": True}


@router.post("/{community_id}/start")
async def start(community_id: str, user: dict = Depends(require_user)):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    handle = supervisor.start(community_id)
    return {"ok": True, "pid": handle.process.pid}


@router.post("/{community_id}/stop")
async def stop(community_id: str, user: dict = Depends(require_user)):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    stopped = supervisor.stop(community_id)
    return {"ok": True, "was_running": stopped}


@router.post("/{community_id}/restart")
async def restart(community_id: str, user: dict = Depends(require_user)):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    handle = supervisor.restart(community_id)
    return {"ok": True, "pid": handle.process.pid}


@router.get("/{community_id}/status")
async def status(community_id: str, user: dict = Depends(require_user)):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    return supervisor.status(community_id)


@router.get("/{community_id}/log")
async def log(community_id: str, lines: int = 200, user: dict = Depends(require_user)):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    return {"log": supervisor.tail_log(community_id, lines=lines)}


@router.get("/{community_id}/members")
async def members(community_id: str, user: dict = Depends(require_user)):
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    return {"members": _fetch_members(community_id, limit=50)}


# ── avatar 서빙 (커뮤니티 격리 주의) ───────────────────────────────

_PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00"
    b"\x03\x00\x01\x08\x00\x01\x10t\x08\xd7\x00\x00\x00\x00IEND\xaeB`\x82"
)


# 별도 라우터 — 공통 prefix 안 타도록 루트에 직접 붙임
avatar_router = APIRouter()


@avatar_router.get("/api/avatar")
async def serve_avatar(
    community: str,
    id: str,
    variant: str = "",
    user: dict = Depends(require_user),
):
    if not accounts.user_can_access(user, community):
        raise HTTPException(403, "no access")

    def _resolve_path():
        from src import community as _comm
        from src.core.profile import load_profile
        profile = load_profile(id) or {}
        fname = profile.get("profile_image_filename") or ""
        target = None
        if fname:
            base, ext = os.path.splitext(fname)
            if variant == "full":
                full_fname = f"{base}-full{ext}"
                target = _comm.get_profile_image_path(full_fname) or _comm.get_profile_image_path(fname)
            else:
                target = _comm.get_profile_image_path(fname)
        if not target:
            target = _comm.find_profile_image(id)
        return target

    target = run_in_community(community, _resolve_path)

    if not target or not os.path.exists(target):
        return Response(
            content=_PLACEHOLDER_PNG,
            media_type="image/png",
            headers={"Cache-Control": "no-cache"},
        )

    with open(target, "rb") as f:
        data = f.read()
    ext = os.path.splitext(target)[1].lower().lstrip(".")
    ctype = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "webp": "image/webp",
    }.get(ext, "application/octet-stream")
    etag = '"' + hashlib.md5(data).hexdigest()[:16] + '"'
    return Response(
        content=data,
        media_type=ctype,
        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"},
    )
