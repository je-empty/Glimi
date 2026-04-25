"""풀렸다 — 화해/해소/관계회복 이벤트 1+."""
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT description FROM events WHERE event_type IN ('화해', '해소', '관계회복') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"description": (row["description"] or "")[:80]}}
    return None


ACHIEVEMENT = Achievement(
    key="reconciliation",
    title="풀렸다",
    description="다툰 친구들이 다시 화해한 순간.",
    icon="🕊️",
    check=check,
)
