"""첫 대화 — 새 친구와 DM 에서 3턴 이상."""
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    personas = [r[0] for r in conn.execute(
        "SELECT name FROM agents WHERE type='persona'"
    ).fetchall()]
    if not personas:
        conn.close()
        return None
    total_owner_msgs = 0
    friend_hit = None
    for name in personas:
        ch = f"dm-{name}"
        cnt = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE channel=? AND speaker=?",
            (ch, user_id)
        ).fetchone()[0]
        total_owner_msgs = max(total_owner_msgs, cnt)
        if cnt >= 3 and friend_hit is None:
            friend_hit = name
    conn.close()
    if friend_hit:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"friend": friend_hit}}
    if total_owner_msgs > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"msgs": total_owner_msgs, "need": 3}}
    return None


ACHIEVEMENT = Achievement(
    key="first_friend_chat",
    title="첫 대화",
    description="새 친구와 DM에서 3턴 이상 대화하기.",
    icon="💬",
    check=check,
)
