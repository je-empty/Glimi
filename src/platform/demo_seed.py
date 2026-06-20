"""첫 실행 시 demo(목업) 커뮤니티 자동 시딩 + registry 등록.

흐름:
  - app.lifespan() 이 첫 실행 1회 ensure_demo_seeded() 호출 (DATA_DIR/.demo_seeded 마커로 가드).
  - communities/demo/ 가 없으면 scripts.seed_demo_mockup.seed("demo") 실행 후
    registry.toml 에 한글 표시 이름/설명 + language="ko" + read_only=true 로 등록.
  - 멱등 + best-effort: 이미 있으면 no-op, 실패해도 startup 을 깨지 않는다 (로그 + 계속).

demo 는 "이 앱이 뭘 하는지" 보여주는 둘러보기 전용 목업 — read_only=true 라
웹 채팅 전송이 차단된다 (chat.py WS 게이트 + 컴포저 비활성 + 배너).
"""
import re

from src.community import COMMUNITIES_DIR, REGISTRY_PATH, _ensure_registry

DEMO_ID = "demo"
_DEMO_NAME = "내 커뮤니티"
_DEMO_DESC = "일상 수다 · 게임 · 맛집 · 주제 없는 아지트"

DEMO_LIVE_ID = "demo-live"
_LIVE_NAME = "내 커뮤니티 (라이브 시연)"
_LIVE_DESC = "친구들과 직접 대화해보는 라이브 시연 — 초대 전용"


def _toml_escape(s: str) -> str:
    """TOML 문자열 이스케이프 — 역슬래시·큰따옴표."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _write_registry_block(cid: str, name: str, description: str,
                          language: str, read_only: bool,
                          invite_required: bool = False) -> None:
    """registry.toml 의 [community.<cid>] 블록을 name/description/language/read_only
    (+ 선택 invite_required) 로 갱신.

    _ensure_registry 가 만든 기본 블록(name=cid, description="")을 통째로 교체.
    communities/routers/communities.py:_update_registry 패턴 + read_only 확장.
    이미 같은 블록이 정확히 있으면 멱등(no-op). invite_required 는 True 일 때만 한 줄
    추가 (기존 demo/demo-en 블록은 그대로 — churn 없음).
    """
    if not REGISTRY_PATH.exists():
        return
    content = REGISTRY_PATH.read_text(encoding="utf-8")
    new_block = (
        f'[community.{cid}]\n'
        f'name = "{_toml_escape(name or cid)}"\n'
        f'description = "{_toml_escape(description)}"\n'
        f'language = "{language}"\n'
        f'read_only = {"true" if read_only else "false"}'
    )
    if invite_required:
        new_block += '\ninvite_required = true'
    if new_block in content:
        return  # 이미 동일 — 멱등

    # 기존 [community.<cid>] 블록(다음 [ 직전까지)을 통째로 치환.
    pattern = re.compile(
        rf'\[community\.{re.escape(cid)}\][^\[]*',
        re.MULTILINE,
    )
    if pattern.search(content):
        content = pattern.sub(new_block + "\n", content)
    else:
        # 블록 자체가 없으면 끝에 추가 (보통 _ensure_registry 가 먼저 만들어줌).
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + new_block + "\n"
    REGISTRY_PATH.write_text(content, encoding="utf-8")


def ensure_demo_seeded() -> bool:
    """demo 커뮤니티가 없으면 시딩 + registry 등록. 반환: 이번 호출에서 새로 시딩했는지.

    멱등: communities/demo/ 가 이미 있으면 no-op (사용자가 데모를 지웠다면
    호출 측 마커가 재시드를 막아준다 — 여기선 디렉터리 존재만 본다).
    best-effort: 어떤 실패도 raise 하지 않는다 (startup 보호).
    """
    try:
        demo_dir = COMMUNITIES_DIR / DEMO_ID
        newly = False
        # 1) demo 디렉터리가 없을 때만 데이터 시딩 (import-safe 한 seed 함수).
        #    이미 있으면 DB 는 건드리지 않는다 (기존 데모 보존).
        if not demo_dir.exists():
            from scripts.seed_demo_mockup import seed as _seed
            _seed(DEMO_ID)
            newly = True

        # 2) registry 의 read_only 목업 메타를 항상 보장한다 — 새로 시딩했든,
        #    이미 존재하든(예: 라이브 서버의 기존 demo). 그래야 배포 후 기존 데모도
        #    읽기 전용으로 전환된다. (_write_registry_block 은 멱등.)
        _ensure_registry(DEMO_ID)
        _write_registry_block(
            DEMO_ID, _DEMO_NAME, _DEMO_DESC, language="ko", read_only=True,
        )
        print(f"[demo_seed] '{DEMO_ID}' 커뮤니티 {'시딩' if newly else 'read_only 메타'} 완료 (목업)")
        return newly
    except Exception as e:  # noqa: BLE001 — startup 을 절대 깨지 않는다
        import traceback
        print(f"[demo_seed] ⚠ demo 시딩 실패 (무시하고 계속): {e}")
        traceback.print_exc()
        return False


def ensure_demo_live_seeded() -> bool:
    """demo 를 채팅 가능한 초대전용 'demo-live'(presenter) 로 복제.

    같은 친구·히스토리(공개 demo 의 DB/아바타 복사) 위에서:
      - read_only=true  → 익명도 둘러보기는 가능 (게이트는 토큰 보유자에게만 입장 허용)
      - invite_required=true → 토큰/오너만 입장 + 채팅 (pages/chat 게이트가 적용)
    실모델 응답은 demo-live/.env 의 ollama 백엔드로 — 기본은 이미 로드된 로컬 모델 공유
    (추가 메모리 0; GLIMI_DEMO_LIVE_MODEL 로 override). 공개 demo 는 그대로 깨끗하게 유지.
    멱등(이미 있으면 .env/registry 만 보장) · best-effort(startup 보호).
    """
    try:
        import os
        import shutil
        demo_dir = COMMUNITIES_DIR / DEMO_ID
        live_dir = COMMUNITIES_DIR / DEMO_LIVE_ID
        if not demo_dir.exists():
            return False  # 공개 demo 가 먼저 시딩돼야 복제 가능
        newly = False
        if not live_dir.exists():
            shutil.copytree(
                demo_dir, live_dir,
                ignore=shutil.ignore_patterns(
                    "*.backup", "*.pre-utc.backup", "backups", "logs", ".DS_Store"),
            )
            newly = True
        # 실모델 백엔드(.env) — 항상 재기록(재배포로 모델 교체 가능).
        model = (os.environ.get("GLIMI_DEMO_LIVE_MODEL") or "gemma4:e4b-it-q4_K_M").strip()
        (live_dir / ".env").write_text(
            "DISCORD_BOT_TOKEN=mockup-no-token\n"
            "GLIMI_LLM_BACKEND=ollama\n"
            f"GLIMI_OLLAMA_MODEL={model}\n",
            encoding="utf-8",
        )
        _ensure_registry(DEMO_LIVE_ID)
        _write_registry_block(
            DEMO_LIVE_ID, _LIVE_NAME, _LIVE_DESC,
            language="ko", read_only=True, invite_required=True,
        )
        print(f"[demo_seed] '{DEMO_LIVE_ID}' {'복제' if newly else '메타'} 완료 "
              f"(초대전용 실모델 시연, model={model})")
        return newly
    except Exception as e:  # noqa: BLE001 — startup 을 절대 깨지 않는다
        import traceback
        print(f"[demo_seed] ⚠ demo-live 복제 실패 (무시하고 계속): {e}")
        traceback.print_exc()
        return False
