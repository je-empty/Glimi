"""인싸의 길 🎈 — 활성 persona 5+ (메타 박살 제외)."""
from typing import Optional
from community import db
from community.achievements.base import Achievement

THRESHOLD = 5


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM agents WHERE type='persona' AND meta_breached_at IS NULL"
        ).fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= THRESHOLD:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt, "threshold": THRESHOLD}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": THRESHOLD}}
    return None


ACHIEVEMENT = Achievement(
    key="many_friends",
    title="인싸의 길 🎈",
    description="다섯 명 이상의 친구와 대화하는 커뮤니티 완성.",
    icon="🎈",
    check=check,
)
