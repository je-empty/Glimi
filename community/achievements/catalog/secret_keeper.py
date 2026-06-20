"""훔쳐보는 관객 🎭 — internal-dm 채널 내 비밀 대화 30+."""
from typing import Optional
from community import db
from community.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations WHERE channel LIKE 'internal-dm-%'"
        ).fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= 30:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    return None


ACHIEVEMENT = Achievement(
    key="secret_keeper",
    title="훔쳐보는 관객 🎭",
    description="친구들끼리의 비밀 대화 30건 이상을 곁눈질했다.",
    icon="🎭",
    check=check,
)
