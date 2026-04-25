"""훔쳐보는 재미 — persona 끼리의 internal-* 비밀 대화 10+ (매니저간 대화 제외)."""
from typing import Optional
from src import db
from src.achievements.base import Achievement
from src.achievements.catalog._shared import is_manager_only_channel


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT channel, COUNT(*) as c FROM conversations "
        "WHERE channel LIKE 'internal-%' GROUP BY channel HAVING c >= 10"
    ).fetchall()
    conn.close()
    persona_channels = [r["channel"] for r in rows if not is_manager_only_channel(r["channel"])]
    if persona_channels:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channels": persona_channels[:5]}}
    return None


ACHIEVEMENT = Achievement(
    key="peek_internal",
    title="훔쳐보는 재미",
    description="친구들끼리 나누는 비밀 대화(internal-*)가 10턴 이상 진행됨.",
    icon="👀",
    check=check,
)
