"""단톡방 체험 — group-* 채널에서 오너 포함 5+ 메시지."""
from typing import Optional
from src import db
from src.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    chs = conn.execute(
        "SELECT DISTINCT channel FROM conversations WHERE channel LIKE 'group-%'"
    ).fetchall()
    max_msgs = 0
    hit_ch = None
    for r in chs:
        ch = r[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE channel=?", (ch,)
        ).fetchone()[0]
        has_owner = conn.execute(
            "SELECT 1 FROM conversations WHERE channel=? AND speaker=? LIMIT 1",
            (ch, user_id)
        ).fetchone()
        if has_owner and total > max_msgs:
            max_msgs = total
            hit_ch = ch
    conn.close()
    if hit_ch and max_msgs >= 5:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channel": hit_ch, "msgs": max_msgs}}
    if hit_ch:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"channel": hit_ch, "msgs": max_msgs, "need": 5}}
    return None


ACHIEVEMENT = Achievement(
    key="group_chat",
    title="단톡방 체험",
    description="친구들과 함께 있는 그룹 채팅에서 5개 이상 메시지 주고받기.",
    icon="🎉",
    check=check,
)
