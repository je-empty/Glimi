"""수다쟁이 💬 — 커뮤니티 전체 대화량 500+."""
from typing import Optional
from src import db
from src.achievements.base import Achievement

THRESHOLD = 500


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= THRESHOLD:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    if cnt > THRESHOLD // 5:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": THRESHOLD}}
    return None


ACHIEVEMENT = Achievement(
    key="chatter",
    title="수다쟁이",
    description="커뮤니티 전체 대화량 500건 돌파.",
    icon="💬",
    check=check,
)
