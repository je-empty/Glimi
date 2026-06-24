"""첫 대화 — 새 친구와 DM 에서 3턴 이상."""
from typing import Optional
from community import db
from community.achievements.base import Achievement


def check(user_id: str) -> Optional[dict]:
    from community.core.channels import _norm_name_for_channel
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
        # raw + normalized 둘 다 매칭 — '유키 아스나' 같은 공백 페르소나 호환
        ch_raw = f"dm-{name}"
        ch_norm = f"dm-{_norm_name_for_channel(name)}"
        if ch_raw == ch_norm:
            placeholders = "?"
            params = (ch_raw, user_id)
        else:
            placeholders = "?,?"
            params = (ch_raw, ch_norm, user_id)
        cnt = conn.execute(
            f"SELECT COUNT(*) FROM conversations WHERE channel IN ({placeholders}) AND speaker=?",
            params
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
