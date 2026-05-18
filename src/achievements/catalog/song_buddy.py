"""음악 친구 — 노래·가사·곡 얘기 10번 이상 나눔."""
from __future__ import annotations

from typing import Optional

from src import db
from src.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM conversations "
        "WHERE (message LIKE '%노래%' OR message LIKE '%가사%' OR message LIKE '%곡%')"
    ).fetchone()[0]
    conn.close()
    if cnt >= 10:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": 10}}
    return None


ACHIEVEMENT = Achievement(
    key="song_buddy",
    title="음악 친구",
    description="노래·가사·곡 얘기 10번 이상 나눔.",
    icon="🎵",
    check=_check,
)
