"""Jinja2 템플릿 환경 — `env` 를 라우터에서 사용.

대시보드 셸은 Glimi Core 정본 (`glimi/dashboard/templates/dashboard/_core.html`)
을 그대로 렌더한다 — 커뮤니티는 `dashboard/index.html` 에서 그걸 extends 하고
커뮤니티 전용 확장(서버 컨트롤 스크립트·PWA)만 블록으로 채운다. 그래서 검색 경로에
커뮤니티 템플릿 + Core 패키지 템플릿을 둘 다 둔다 (이름 충돌 없음: `_core.html` 은
Core 에만, `index.html`/`base.html` 등은 커뮤니티에만)."""
import os
import time
from pathlib import Path

import glimi.dashboard as _dashboard
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent
# Core 가 ship 하는 정본 대시보드 템플릿 디렉토리 (설치된 glimi[dashboard] 패키지).
_DASH_TEMPLATES = Path(_dashboard.__file__).resolve().parent / "templates"

env = Jinja2Templates(directory=[str(TEMPLATES_DIR), str(_DASH_TEMPLATES)])

# 정적 자산 캐시 버스팅 — 서버 시작 시각. 재시작(=배포)마다 바뀌어 브라우저가 CSS/JS 재페치.
# 템플릿에서 `/static/...?v={{ asset_v }}` 로 사용.
env.env.globals["asset_v"] = str(int(time.time()))

# 공개 데모 배포에서만 설정 — 상단 랜딩(glimi.iruyo.com)으로 돌아가는 링크 노출.
# 미설정(로컬/OSS)이면 빈 문자열 → 템플릿이 링크를 렌더하지 않는다.
env.env.globals["landing_url"] = os.environ.get("GLIMI_LANDING_URL", "")
