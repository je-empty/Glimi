"""튜토리얼 수료 — 유나·하나와 첫 만남 완료 + 첫 친구 만들기."""
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT value FROM meta WHERE key='tutorial_phase'"
    ).fetchone()
    conn.close()
    if row and row["value"] == "complete":
        return {"state": "done", "mark_completed": True, "mark_unlocked": True}
    return None


ACHIEVEMENT = Achievement(
    key="tutorial_done",
    title="튜토리얼 수료",
    description="유나·하나와 첫 만남을 완료하고 첫 친구를 만들었다.",
    icon="🎓",
    check=check,
)
