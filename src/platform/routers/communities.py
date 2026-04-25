"""커뮤니티 CRUD + 봇 start/stop API."""
import hashlib
import json as _json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from src.community import (
    COMMUNITIES_DIR,
    init_community,
    list_communities,
    REGISTRY_PATH,
)

from .. import accounts
from ..auth import require_user
from ..community_ctx import run_in_community
from ..discord_verify import verify_token_sync, wipe_glimi_channels_sync
from ..supervisor import supervisor

router = APIRouter(prefix="/api/communities")


class OwnerProfileIn(BaseModel):
    name: str
    nickname: str | None = None
    birth: str | None = None  # "2001-01-01" or raw "20010101"
    gender: str | None = None  # "남" | "여" | ""


class CreateCommunityIn(BaseModel):
    id: str
    name: str | None = None  # 표시용 이름 (한글 등). 없으면 id 로 폴백
    description: str = ""
    language: str = "en"
    token: str  # Discord bot token
    owner: OwnerProfileIn
    clean_existing_channels: bool = False
    grant_to_user: str | None = None


class VerifyTokenIn(BaseModel):
    token: str


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
    # 정렬: 실행 중 먼저 → 알파벳
    visible.sort(key=lambda c: (
        0 if c.get("running") else 1,
        c.get("id", ""),
    ))
    return visible


def _normalize_birth(raw: str) -> str:
    """20010101 → 2001-01-01. 이미 하이픈 있으면 그대로."""
    if not raw:
        return ""
    digits = raw.replace("-", "").replace("/", "").replace(".", "").strip()
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


def _save_owner_profile(cid: str, name: str, nickname: str, birth: str, gender: str) -> None:
    """오너 프로필을 커뮤니티 DB 의 users + meta.active_user_id 로 저장.
    TUI wizard._save_owner_profile 이식.
    """
    # DB 초기화 먼저 — env + set_community + init_db 필요
    old = os.environ.get("GLIMI_COMMUNITY", "")
    os.environ["GLIMI_COMMUNITY"] = cid
    try:
        from src import community as _comm
        from src import db as _db
        _comm.set_community(cid)
        _db.DB_PATH = None
        _db.init_db()

        age = None
        birth_year = None
        birth_norm = _normalize_birth(birth)
        if birth_norm:
            try:
                bd = datetime.strptime(birth_norm, "%Y-%m-%d")
                birth_year = bd.year
                age = datetime.now().year - birth_year
            except ValueError:
                pass

        owner_id = name.lower().replace(" ", "_")
        personality = _json.dumps(
            {"nickname": nickname, "gender": gender},
            ensure_ascii=False,
        ) if (nickname or gender) else None

        db_path = COMMUNITIES_DIR / cid / "community.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO users (id, name, birth_year, age, personality) VALUES (?, ?, ?, ?, ?)",
                (owner_id, name, birth_year, age, personality),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('active_user_id', ?)",
                (owner_id,),
            )
            conn.commit()
        finally:
            conn.close()
    finally:
        if old:
            os.environ["GLIMI_COMMUNITY"] = old
            from src import community as _comm
            _comm.set_community(old)


def _toml_escape(s: str) -> str:
    """TOML 문자열 이스케이프 — 큰따옴표·역슬래시 처리."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _update_registry(cid: str, name: str, description: str, language: str) -> None:
    """registry.toml 의 community.{cid} 블록을 name/description/language 로 업데이트.
    init_community 가 만든 기본 블록을 교체.
    """
    if not REGISTRY_PATH.exists():
        return
    content = REGISTRY_PATH.read_text()
    # init_community 가 만든 초기 블록: name=cid, description=""
    old_block = f'[community.{cid}]\nname = "{cid}"\ndescription = ""'
    new_block = (
        f'[community.{cid}]\n'
        f'name = "{_toml_escape(name or cid)}"\n'
        f'description = "{_toml_escape(description)}"\n'
        f'language = "{language}"'
    )
    if old_block in content:
        content = content.replace(old_block, new_block)
        REGISTRY_PATH.write_text(content)


def _run_db_init(cid: str) -> tuple[bool, str]:
    """신규 커뮤니티용 DB 초기화. subprocess 로 격리 — main process 의
    전역 community state 오염 방지.

    레거시 JSON → DB 마이그레이션은 더 이상 호출 안 함 (profiles/ 가 있는
    과거 설치 업그레이드에만 필요했음 — 신규 커뮤니티엔 무관)."""
    env = os.environ.copy()
    env["GLIMI_COMMUNITY"] = cid
    proc = subprocess.run(
        [
            sys.executable, "-c",
            "from src import community, db; "
            f"community.set_community('{cid}'); "
            "db.init_db()"
        ],
        capture_output=True, text=True, env=env,
        cwd=str(COMMUNITIES_DIR.parent),
        timeout=30,
    )
    return (proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:])


@router.post("/verify_token")
async def verify_token_endpoint(data: VerifyTokenIn, user: dict = Depends(require_user)):
    """Discord 봇 토큰 검증 — 봇명/서버명/권한/기존채널 반환."""
    from fastapi.concurrency import run_in_threadpool
    return await run_in_threadpool(verify_token_sync, data.token, 15.0)


@router.get("/new_defaults")
async def new_defaults(id: str = "", user: dict = Depends(require_user)):
    """로컬 dev 편의 — `dev/test_defaults.json` 에 저장된 커뮤니티 id 별 기본값 반환.
    git ignored. 이 맥에서만 유효. 등록 안 된 id 는 빈 dict.

    예: {"test": {"token": "MTQ..."}}  →  GET /api/communities/new_defaults?id=test
    """
    if not id:
        return {}
    defaults_file = COMMUNITIES_DIR.parent / "dev" / "test_defaults.json"
    if not defaults_file.exists():
        return {}
    try:
        with open(defaults_file, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception:
        return {}
    return data.get(id, {})


@router.post("")
async def create(data: CreateCommunityIn, user: dict = Depends(require_user)):
    from dotenv import set_key

    # ── 검증 ──
    if not data.id:
        raise HTTPException(400, "id required")
    if any(c["id"] == data.id for c in list_communities()):
        raise HTTPException(400, "already exists")
    if not data.id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "id must be alphanumeric with -/_")
    if not data.token.strip():
        raise HTTPException(400, "discord token required")
    if not data.owner.name.strip():
        raise HTTPException(400, "owner name required")

    # ── 1. community 디렉터리 + 기본 파일 ──
    init_community(data.id)

    # ── 1a. (옵션) 기존 Discord glimi-* 채널·카테고리 즉시 삭제 ──
    wipe_summary = None
    if data.clean_existing_channels:
        from fastapi.concurrency import run_in_threadpool
        wipe_summary = await run_in_threadpool(wipe_glimi_channels_sync, data.token.strip(), 30.0)
        if not wipe_summary.get("ok"):
            # 삭제 실패해도 진행하되 경고 수집
            wipe_summary.setdefault("errors", []).append("일부 실패 — 봇 첫 기동 시 잔여분 자동 정리됨")
        # 잔여분 대비 .clean-channels 플래그도 남겨둠 — orphan 채널 추후 정리
        log_dir = COMMUNITIES_DIR / data.id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / ".clean-channels").touch()

    # ── 2. registry name + description + language ──
    _update_registry(data.id, data.name or data.id, data.description, data.language)

    # ── 3. .env 에 토큰 기록 ──
    env_path = COMMUNITIES_DIR / data.id / ".env"
    set_key(str(env_path), "DISCORD_BOT_TOKEN", data.token.strip())

    # ── 4. 오너 프로필 저장 ──
    _save_owner_profile(
        data.id,
        data.owner.name.strip(),
        (data.owner.nickname or "").strip(),
        (data.owner.birth or "").strip(),
        (data.owner.gender or "").strip(),
    )

    # ── 5. DB 초기화 (subprocess) ──
    from fastapi.concurrency import run_in_threadpool
    ok, log = await run_in_threadpool(_run_db_init, data.id)
    if not ok:
        return {
            "ok": False,
            "id": data.id,
            "warning": "DB 초기화 실패",
            "log": log,
        }

    # ── 6. 접근 권한 부여 ──
    accounts.grant_community(user["id"], data.id)
    if data.grant_to_user and user.get("role") == "admin":
        target = accounts.get_user(data.grant_to_user)
        if target:
            accounts.grant_community(target["id"], data.id)

    return {
        "ok": True,
        "id": data.id,
        "wipe": wipe_summary,
    }


@router.delete("/{community_id}")
async def delete(
    community_id: str,
    wipe_discord: bool = False,
    user: dict = Depends(require_user),
):
    """커뮤니티 삭제. wipe_discord=true 면 .env 토큰으로 디스코드 channels 까지 정리."""
    if not accounts.user_can_access(user, community_id):
        raise HTTPException(403, "no access")
    if supervisor.status(community_id).get("running"):
        supervisor.stop(community_id)

    cdir = COMMUNITIES_DIR / community_id
    wipe_summary = None

    # ── 1. 옵션 — Discord 채널 정리 (dir 지우기 전에 .env 에서 토큰 읽기) ──
    if wipe_discord and cdir.exists():
        env_file = cdir / ".env"
        token = ""
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("DISCORD_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip("'\"")
                    break
        if token:
            from fastapi.concurrency import run_in_threadpool
            wipe_summary = await run_in_threadpool(wipe_glimi_channels_sync, token, 30.0)
        else:
            wipe_summary = {"ok": False, "errors": [".env 에 DISCORD_BOT_TOKEN 없음"]}

    # ── 2. 디렉터리 삭제 ──
    if cdir.exists():
        shutil.rmtree(cdir)

    # ── 3. registry 정리 ──
    if REGISTRY_PATH.exists():
        content = REGISTRY_PATH.read_text()
        import re
        pattern = re.compile(
            rf'\n?\[community\.{re.escape(community_id)}\][^\[]*',
            re.MULTILINE,
        )
        content = pattern.sub("", content)
        pattern2 = re.compile(
            rf'\n?\[communities\.{re.escape(community_id)}\][^\[]*',
            re.MULTILINE,
        )
        content = pattern2.sub("", content)
        REGISTRY_PATH.write_text(content)

    return {"ok": True, "wipe": wipe_summary}


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
    st = supervisor.status(community_id)
    # demo 커뮤니티는 시연용 — 실제 봇 없어도 가동중 으로 표시.
    if community_id == "demo":
        import time as _t
        st = dict(st or {})
        st["running"] = True
        st["uptime_sec"] = int(_t.time()) % (3600 * 24)  # 24h 주기로 돌아가는 uptime
    return st


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
    # no-cache: 브라우저가 매 요청마다 ETag 로 revalidate 하도록 강제. 컨텐츠 변경 시
    # ETag 가 바뀌어 즉시 새 이미지 로드. (max-age=3600 시 sample 교체 후 1시간 동안
    # 옛 아바타 그대로 보이는 캐시 stickiness 회귀 발생.)
    return Response(
        content=data,
        media_type=ctype,
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )
