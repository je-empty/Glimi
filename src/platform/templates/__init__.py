"""Jinja2 템플릿 환경 — `env` 를 라우터에서 사용."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent

env = Jinja2Templates(directory=str(TEMPLATES_DIR))
