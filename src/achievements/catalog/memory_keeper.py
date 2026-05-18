"""추억 보관함 — 고정된(pinned) 기억 3개 이상."""
from __future__ import annotations

from typing import Optional

from src import db
from src.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE is_pinned=1"
        ).fetchone()[0]
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= 3:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": 3}}
    return None


ACHIEVEMENT = Achievement(
    key="memory_keeper",
    title="추억 보관함",
    description="고정된(pinned) 기억 3개 이상.",
    icon="📌",
    check=_check,
)
