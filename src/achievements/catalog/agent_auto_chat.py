"""자율 사교 — persona 간 자율 대화 진행 중 (running)."""
from typing import Optional
from src import db
from src.achievements.base import Achievement
from src.achievements.catalog._shared import is_manager_only_channel


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT channel FROM channels WHERE channel LIKE 'internal-%' AND status='running'"
    ).fetchall()
    conn.close()
    for r in rows:
        if not is_manager_only_channel(r["channel"]):
            return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                    "progress_data": {"channel": r["channel"]}}
    return None


ACHIEVEMENT = Achievement(
    key="agent_auto_chat",
    title="자율 사교",
    description="친구들끼리 자동으로 대화를 시작한 순간.",
    icon="🤝",
    check=check,
)
