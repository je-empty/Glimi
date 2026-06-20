"""첫 다툼 — persona 간 갈등/다툼/오해 이벤트 1+."""
from typing import Optional
from community import db
from community.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT participants, description FROM events "
            "WHERE event_type IN ('갈등', '다툼', '오해') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"description": (row["description"] or "")[:80]}}
    return None


ACHIEVEMENT = Achievement(
    key="first_conflict",
    title="첫 다툼",
    description="친구들 사이에 처음 갈등이 생겼다. 관계는 이제부터가 진짜.",
    icon="⚡",
    check=check,
)
