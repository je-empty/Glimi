"""지속되는 관계 — 한 friend dm 첫메시지 ~ 최근메시지 ≥ 3일."""
from datetime import datetime
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT channel, MIN(timestamp) as first, MAX(timestamp) as last "
        "FROM conversations WHERE channel LIKE 'dm-%' GROUP BY channel"
    ).fetchall()
    conn.close()
    best = None
    for r in rows:
        try:
            first = datetime.fromisoformat(r["first"])
            last = datetime.fromisoformat(r["last"])
            days = (last - first).total_seconds() / 86400
            if days >= 3 and (best is None or days > best[1]):
                best = (r["channel"], days)
        except Exception:
            continue
    if best:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channel": best[0], "days": round(best[1], 1)}}
    return None


ACHIEVEMENT = Achievement(
    key="long_relationship",
    title="지속되는 관계",
    description="한 친구와 3일 이상 이어진 대화.",
    icon="🌱",
    check=check,
)
