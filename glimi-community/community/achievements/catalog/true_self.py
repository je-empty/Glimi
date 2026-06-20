"""가면 벗기기 — 친구의 감정이 격해진 순간 (강도 8 이상)."""
from __future__ import annotations

from typing import Optional

from community import db
from community.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    cnt = conn.execute(
        "SELECT COUNT(DISTINCT id) FROM agents "
        "WHERE type='persona' AND emotion_intensity >= 8"
    ).fetchone()[0]
    conn.close()
    if cnt >= 1:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    return None


ACHIEVEMENT = Achievement(
    key="true_self",
    title="가면 벗기기",
    description="친구의 감정이 격해진 순간 (강도 8 이상).",
    icon="🎭",
    check=_check,
)
