"""캐릭터 디자이너 — 다섯 명 이상의 친구를 직접 만들었다."""
from __future__ import annotations

from typing import Optional

from community import db
from community.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM agents WHERE type='persona' AND status='active'"
    ).fetchone()[0]
    conn.close()
    if cnt >= 5:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": 5}}
    return None


ACHIEVEMENT = Achievement(
    key="character_designer",
    title="캐릭터 디자이너",
    description="다섯 명 이상의 친구를 직접 만들었다.",
    icon="🎨",
    check=_check,
)
