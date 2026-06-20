"""제 4 의 벽 박살 — persona 자기 자각 발화로 잠금된 케이스 (`agents.meta_breached_at`)."""
from typing import Optional
from community import db
from community.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, meta_breached_at FROM agents "
            "WHERE type='persona' AND meta_breached_at IS NOT NULL "
            "ORDER BY meta_breached_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"name": row["name"], "at": row["meta_breached_at"]}}
    return None


ACHIEVEMENT = Achievement(
    key="meta_breach",
    title="제4의 벽 박살 🔨",
    description="친구 한 명의 환상을 깼다. 그 친구는 기억을 잃고 사라졌다.",
    icon="💥",
    check=check,
)
