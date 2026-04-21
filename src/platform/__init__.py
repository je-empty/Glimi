"""Glimi Platform — 웹 기반 커뮤니티 관리 + 대시보드.

FastAPI 기반 control plane. 각 커뮤니티 봇은 supervisor 가 subprocess 로 관리.

진입점:
  python -m src.platform               → uvicorn 포그라운드 구동
  python -m src.platform.accounts ...  → 계정 CLI
"""
