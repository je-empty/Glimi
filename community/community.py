"""
Project Glimi — 커뮤니티 컨텍스트 관리

커뮤니티 = DB 하나 + .env 하나 + 프로필 이미지 + 로그
communities/ 디렉토리 아래 커뮤니티별 서브디렉토리로 격리.

구조:
  communities/
  ├── registry.toml        ← 커뮤니티 목록 + default
  ├── my-server/
  │   ├── .env             ← DISCORD_BOT_TOKEN
  │   ├── community.db     ← SQLite
  │   ├── profile_images/  ← 에이전트 프로필 이미지
  │   └── logs/
  └── another-server/
      └── ...

사용:
  GLIMI_COMMUNITY=my-server ./scripts/run.sh
  ./scripts/run.sh my-server
"""
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # fallback

PROJECT_ROOT = Path(__file__).parent.parent
# Communities live in PROJECT_ROOT/communities by default. GLIMI_COMMUNITIES_DIR
# overrides it so multiple platform instances can serve disjoint community sets
# from one checkout — e.g. a public demo-only instance (communities-demo/) vs the
# owner's private real-use instance (communities/). Registry derives from it.
COMMUNITIES_DIR = Path(os.environ.get("GLIMI_COMMUNITIES_DIR") or (PROJECT_ROOT / "communities"))
ASSETS_DIR = PROJECT_ROOT / "assets"
REGISTRY_PATH = COMMUNITIES_DIR / "registry.toml"

_current_id: Optional[str] = None


# ── 커뮤니티 ID 결정 ─────────────────────────────────────

def set_community(community_id: str):
    """커뮤니티 ID 설정 (프로세스 시작 시 1회) + 언어 연동"""
    global _current_id
    _current_id = community_id
    os.environ["GLIMI_COMMUNITY"] = community_id
    # 에이전트 언어 연동 (서버별)
    lang = get_language()
    try:
        from community.i18n import set_agent_language
        set_agent_language(lang)
    except ImportError:
        pass


def get_community_id() -> str:
    """현재 커뮤니티 ID 반환"""
    global _current_id
    if _current_id:
        return _current_id

    # 1. 환경변수
    env_id = os.environ.get("GLIMI_COMMUNITY")
    if env_id:
        _current_id = env_id
        return env_id

    # 2. registry.toml default
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "rb") as f:
            registry = tomllib.load(f)
        default = registry.get("default")
        if default:
            _current_id = default
            return default

    # 3. 첫 번째 커뮤니티
    for d in sorted(COMMUNITIES_DIR.iterdir()) if COMMUNITIES_DIR.exists() else []:
        if d.is_dir() and not d.name.startswith("."):
            _current_id = d.name
            return d.name

    # 4. 없으면 default
    _current_id = "default"
    return "default"


def get_language() -> str:
    """현재 커뮤니티의 언어 설정 반환 (기본: en)"""
    cid = get_community_id()
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "rb") as f:
            registry = tomllib.load(f)
        info = registry.get("community", {}).get(cid, {})
        return info.get("language", "en")
    return "en"


def is_read_only(community_id: Optional[str] = None) -> bool:
    """커뮤니티가 read-only(데모/목업 — 둘러보기 전용)인지 여부 (기본: False).
    registry.toml `[community.<id>] read_only = true` 로 표시. 인자 없으면 현재 커뮤니티."""
    cid = community_id or get_community_id()
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "rb") as f:
            registry = tomllib.load(f)
        info = registry.get("community", {}).get(cid, {})
        return bool(info.get("read_only", False))
    return False


# ── 경로 헬퍼 ────────────────────────────────────────────

def get_community_dir() -> Path:
    return COMMUNITIES_DIR / get_community_id()


def get_db_path() -> str:
    return str(get_community_dir() / "community.db")


def get_env_path() -> str:
    return str(get_community_dir() / ".env")


def is_maintenance_mode() -> bool:
    """대시보드 sync/scan/restore 중이면 True. 봇 루프 전반에서 이 플래그 체크 → 작업 중엔 agent 대화·tool 실행 전부 pause.
    DB·Discord 상태 변경 와중에 봇이 새 메시지 찍으면 불일치."""
    try:
        flag = get_community_dir() / "logs" / ".maintenance"
        return flag.exists()
    except Exception:
        return False


def get_log_dir() -> str:
    return str(get_community_dir() / "logs")


def get_profile_images_dir() -> Path:
    cdir = get_community_dir()
    new_dir = cdir / "profile_images"
    # 레거시 avatars/ 디렉토리가 있으면 이관 (1회 자동)
    legacy = cdir / "avatars"
    if legacy.exists() and not new_dir.exists():
        try:
            legacy.rename(new_dir)
        except Exception:
            new_dir.mkdir(exist_ok=True)
    return new_dir


def get_profile_image_path(filename: str) -> Optional[str]:
    """프로필 이미지 경로 — 커뮤니티 우선, assets 폴백"""
    # 1. 커뮤니티별 프로필 이미지
    community_path = get_profile_images_dir() / filename
    if community_path.exists():
        return str(community_path)
    # 2. 공유 assets 폴백
    assets_path = ASSETS_DIR / "profile_images" / filename
    if assets_path.exists():
        return str(assets_path)
    # 3. sample 카탈로그 폴백 — DB 에 sample 파일명이 그대로 저장된 경우
    # (create_agent_profile JSON 에 sample 파일명이 들어가고 set_profile_image 가
    #  아직 안 불렸거나 실패한 과도기 상태)
    sample_path = ASSETS_DIR / "sample_profile_images" / filename
    if sample_path.exists():
        return str(sample_path)
    return None


def find_profile_image(agent_id: str) -> Optional[str]:
    """agent_id로 프로필 이미지 파일 찾기 (확장자 자동 스캔)"""
    for ext in ("png", "jpg", "jpeg", "webp"):
        fname = f"{agent_id}.{ext}"
        path = get_profile_image_path(fname)
        if path:
            return path
    return None


# ── 커뮤니티 관리 ────────────────────────────────────────

def init_community(community_id: str, copy_assets: bool = True):
    """새 커뮤니티 디렉토리 초기화"""
    COMMUNITIES_DIR.mkdir(parents=True, exist_ok=True)
    cdir = COMMUNITIES_DIR / community_id
    cdir.mkdir(exist_ok=True)
    # 레거시 avatars/ → profile_images/ 자동 이관
    legacy = cdir / "avatars"
    new_dir = cdir / "profile_images"
    if legacy.exists() and not new_dir.exists():
        try:
            legacy.rename(new_dir)
        except Exception:
            pass
    new_dir.mkdir(exist_ok=True)
    (cdir / "logs").mkdir(exist_ok=True)

    # .env 템플릿
    env_path = cdir / ".env"
    if not env_path.exists():
        example = PROJECT_ROOT / "examples" / "community.example" / ".env.example"
        if example.exists():
            shutil.copy2(example, env_path)
        else:
            env_path.write_text(
                "# 디스코드 봇 토큰 (필수)\n"
                "DISCORD_BOT_TOKEN=\n\n"
                "# 오너 디스코드 오너 ID (선택)\n"
                "# DISCORD_OWNER_ID=\n"
            )

    # 기본 프로필 이미지 복사
    if copy_assets:
        src_images = ASSETS_DIR / "profile_images"
        if src_images.exists():
            for img in src_images.iterdir():
                if img.is_file() and not (new_dir / img.name).exists():
                    shutil.copy2(img, new_dir / img.name)

    # registry.toml 업데이트
    _ensure_registry(community_id)
    print(f"[Community] 초기화 완료: {community_id} ({cdir})")


def list_communities() -> list[dict]:
    """등록된 커뮤니티 목록"""
    if not COMMUNITIES_DIR.exists():
        return []
    registry = _load_registry()
    default_id = registry.get("default", "")
    communities = []
    for d in sorted(COMMUNITIES_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        info = registry.get("community", {}).get(d.name, {})
        communities.append({
            "id": d.name,
            "name": info.get("name", d.name),
            "description": info.get("description", ""),
            "is_default": d.name == default_id,
            "read_only": bool(info.get("read_only", False)),
            "language": info.get("language", ""),
            "has_db": (d / "community.db").exists(),
            "has_env": (d / ".env").exists(),
        })
    return communities


def export_community(community_id: str, output_dir: str):
    """커뮤니티 전체를 디렉토리로 내보내기 (DB + 프로필 이미지)"""
    src_dir = COMMUNITIES_DIR / community_id
    if not src_dir.exists():
        print(f"커뮤니티 없음: {community_id}")
        return

    dst = Path(output_dir)
    dst.mkdir(parents=True, exist_ok=True)

    # DB 복사
    db_src = src_dir / "community.db"
    if db_src.exists():
        shutil.copy2(db_src, dst / "community.db")

    # 프로필 이미지 복사 (신규/레거시 둘 다 지원)
    for sub in ("profile_images", "avatars"):
        images_src = src_dir / sub
        if images_src.exists():
            images_dst = dst / "profile_images"
            if images_dst.exists():
                shutil.rmtree(images_dst)
            shutil.copytree(images_src, images_dst)
            break

    print(f"[Community] export 완료: {community_id} → {output_dir}")


def import_community(input_dir: str, community_id: str):
    """디렉토리에서 커뮤니티 가져오기"""
    src = Path(input_dir)
    if not community.exists():
        print(f"경로 없음: {input_dir}")
        return

    init_community(community_id, copy_assets=False)
    dst = COMMUNITIES_DIR / community_id
    dst_images = dst / "profile_images"
    dst_images.mkdir(exist_ok=True)

    # DB 복사
    db_src = src / "community.db"
    if db_src.exists():
        shutil.copy2(db_src, dst / "community.db")

    # 프로필 이미지 복사 (신규/레거시 둘 다 지원)
    for sub in ("profile_images", "avatars"):
        images_src = src / sub
        if images_src.exists():
            for img in images_src.iterdir():
                if img.is_file():
                    shutil.copy2(img, dst_images / img.name)
            break

    print(f"[Community] import 완료: {input_dir} → {community_id}")


# ── 내부 헬퍼 ────────────────────────────────────────────

def _load_registry() -> dict:
    if REGISTRY_PATH.exists():
        with open(REGISTRY_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def _ensure_registry(community_id: str):
    """registry.toml에 커뮤니티 항목 추가 (없으면 생성)"""
    COMMUNITIES_DIR.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        REGISTRY_PATH.write_text(
            f'default = "{community_id}"\n\n'
            f'[community.{community_id}]\n'
            f'name = "{community_id}"\n'
            f'description = ""\n'
        )
        return

    content = REGISTRY_PATH.read_text()
    if f"[community.{community_id}]" not in content:
        content += (
            f'\n[community.{community_id}]\n'
            f'name = "{community_id}"\n'
            f'description = ""\n'
        )
        REGISTRY_PATH.write_text(content)


# ── 디렉토리 자동 생성 ──────────────────────────────────

def ensure_dirs():
    """현재 커뮤니티의 필수 디렉토리 보장"""
    cdir = get_community_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    # 레거시 이관 겸 신규 생성
    get_profile_images_dir().mkdir(exist_ok=True)
    (cdir / "logs").mkdir(exist_ok=True)


# ── CLI 진입점 ───────────────────────────────────────────

def main():
    """커뮤니티 관리 CLI"""
    if len(sys.argv) < 2:
        _print_usage()
        return

    cmd = sys.argv[1]

    if cmd == "list":
        communities = list_communities()
        if not communities:
            print("등록된 커뮤니티 없음")
            return
        for c in communities:
            default = " (default)" if c["is_default"] else ""
            db_status = "DB" if c["has_db"] else "no DB"
            env_status = ".env" if c["has_env"] else "no .env"
            print(f"  {c['id']}{default} — {c['name']} [{db_status}, {env_status}]")

    elif cmd == "init":
        if len(sys.argv) < 3:
            print("사용: python -m community.community init <community_id>")
            return
        init_community(sys.argv[2])

    elif cmd == "export":
        if len(sys.argv) < 4:
            print("사용: python -m community.community export <community_id> <output_dir>")
            return
        export_community(sys.argv[2], sys.argv[3])

    elif cmd == "import":
        if len(sys.argv) < 4:
            print("사용: python -m community.community import <input_dir> <community_id>")
            return
        import_community(sys.argv[2], sys.argv[3])

    else:
        _print_usage()


def _print_usage():
    print("Project Glimi — 커뮤니티 관리")
    print()
    print("사용:")
    print("  python -m community.community list                          커뮤니티 목록")
    print("  python -m community.community init <id>                     새 커뮤니티 초기화")
    print("  python -m community.community export <id> <output_dir>      커뮤니티 내보내기")
    print("  python -m community.community import <input_dir> <id>       커뮤니티 가져오기")


if __name__ == "__main__":
    main()
