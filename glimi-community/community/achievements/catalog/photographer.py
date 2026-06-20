"""프로필 카메라 — 친구의 프로필 사진을 직접 정해주었다."""
from __future__ import annotations

from typing import Optional

from community import db
from community.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM agents WHERE type='persona' AND sample_source_file IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    if cnt >= 1:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    return None


ACHIEVEMENT = Achievement(
    key="photographer",
    title="프로필 카메라",
    description="친구의 프로필 사진을 직접 정해주었다.",
    icon="📸",
    check=_check,
)
