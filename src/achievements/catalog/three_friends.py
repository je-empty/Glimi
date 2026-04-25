"""세 명의 친구 — 서로 다른 persona 3명과 각각 1+ DM."""
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    personas = [r[0] for r in conn.execute(
        "SELECT name FROM agents WHERE type='persona'"
    ).fetchall()]
    talked = []
    for name in personas:
        ch = f"dm-{name}"
        has = conn.execute(
            "SELECT 1 FROM conversations WHERE channel=? AND speaker=? LIMIT 1",
            (ch, user_id)
        ).fetchone()
        if has:
            talked.append(name)
    conn.close()
    if not talked:
        return None
    if len(talked) >= 3:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"talked_to": talked}}
    return {"state": "unlocked", "mark_unlocked": True,
            "progress_data": {"talked_to": talked, "need": 3}}


ACHIEVEMENT = Achievement(
    key="three_friends",
    title="세 명의 친구",
    description="서로 다른 세 명의 친구와 대화 나누기.",
    icon="👥",
    check=check,
)
