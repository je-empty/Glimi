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
_DEMO_NAME = "데모 커뮤니티"
_DEMO_DESC = "Glimi 가 뭘 하는지 둘러보는 목업 — 메시지 전송은 비활성화된 읽기 전용 쇼케이스예요."


def _toml_escape(s: str) -> str:
    """TOML 문자열 이스케이프 — 역슬래시·큰따옴표."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _write_registry_block(cid: str, name: str, description: str,
                          language: str, read_only: bool) -> None:
    """registry.toml 의 [community.<cid>] 블록을 name/description/language/read_only 로 갱신.

    _ensure_registry 가 만든 기본 블록(name=cid, description="")을 통째로 교체.
    communities/routers/communities.py:_update_registry 패턴 + read_only 확장.
    이미 같은 블록이 정확히 있으면 멱등(no-op).
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
        if demo_dir.exists():
            return False  # 이미 존재 — 멱등 no-op

        # 1) 데이터 시딩 (import-safe 한 seed 함수 호출)
        from scripts.seed_demo_mockup import seed as _seed
        _seed(DEMO_ID)

        # 2) registry 기본 블록 보장 후 한글 메타 + read_only 로 갱신
        _ensure_registry(DEMO_ID)
        _write_registry_block(
            DEMO_ID, _DEMO_NAME, _DEMO_DESC, language="ko", read_only=True,
        )
        print(f"[demo_seed] '{DEMO_ID}' 커뮤니티 시딩 완료 (read_only 목업)")
        return True
    except Exception as e:  # noqa: BLE001 — startup 을 절대 깨지 않는다
        import traceback
        print(f"[demo_seed] ⚠ demo 시딩 실패 (무시하고 계속): {e}")
        traceback.print_exc()
        return False
