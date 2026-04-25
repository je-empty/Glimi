"""새벽의 친구 🌙 — 새벽 0-5시 오너 발화 10+."""
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations WHERE speaker=? "
            "AND CAST(strftime('%H', timestamp) AS INTEGER) BETWEEN 0 AND 5",
            (user_id,),
        ).fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= 10:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    return None


ACHIEVEMENT = Achievement(
    key="late_night",
    title="새벽의 친구",
    description="새벽 0시-5시에 10번 이상 대화. 진짜 가까운 사이만 가능.",
    icon="🌙",
    check=check,
)
