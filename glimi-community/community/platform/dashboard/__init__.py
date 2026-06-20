"""Glimi Dashboard 로직 — 구 scripts/web_dashboard.py 에서 이관.

- context.py: 커뮤니티 전환 + reader-writer lock
- api.py: GET 엔드포인트 (read-only)
- actions.py: POST 엔드포인트 (mutations)
"""
from . import api, actions, context  # noqa: F401
