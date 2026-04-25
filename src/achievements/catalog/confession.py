"""마음 열기 — 고백/마음표현/짝사랑 이벤트 1+."""
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT description FROM events WHERE event_type IN ('고백', '마음표현', '짝사랑') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"description": (row["description"] or "")[:80]}}
    return None


ACHIEVEMENT = Achievement(
    key="confession",
    title="마음 열기",
    description="누군가 용기 내서 마음을 고백했다.",
    icon="💗",
    check=check,
)
