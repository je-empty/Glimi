#!/usr/bin/env python3
"""
textual-serve wrapper — src/tui/dashboard.py 를 브라우저에서 보여줌.

포트: 8766 (웹 대시보드 8765와 분리)
실행: python3 scripts/serve_dashboard.py
접속: http://localhost:8766
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Glimi 환경설정
os.environ.setdefault("GLIMI_COMMUNITY", "qa")
os.chdir(str(ROOT))

from textual_serve.server import Server

# Textual 앱을 subprocess로 기동 — GLIMI_COMMUNITY 환경변수 전파됨
command = f"{sys.executable} -m src.tui.dashboard qa"

server = Server(
    command=command,
    host="127.0.0.1",
    port=8766,
    title="Glimi QA Dashboard (TUI)",
)

if __name__ == "__main__":
    print(f"[serve_dashboard] Serving TUI on http://127.0.0.1:8766")
    server.serve()
