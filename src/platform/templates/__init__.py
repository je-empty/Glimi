"""Jinja2 템플릿 환경 — `env` 를 라우터에서 사용."""
import time
from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent

env = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 정적 자산 캐시 버스팅 — 서버 시작 시각. 재시작(=배포)마다 바뀌어 브라우저가 CSS/JS 재페치.
# 템플릿에서 `/static/...?v={{ asset_v }}` 로 사용.
env.env.globals["asset_v"] = str(int(time.time()))
