"""절친 — 한 친구와의 친밀도가 90 이상에 도달."""
from __future__ import annotations

from typing import Optional

from src import db
from src.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT r.intimacy_score, r.agent_a, r.agent_b "
        "FROM relationships r WHERE r.intimacy_score >= 90 "
        "AND ((r.agent_a=? AND r.agent_b LIKE 'agent-persona-%') "
        "  OR (r.agent_b=? AND r.agent_a LIKE 'agent-persona-%'))",
        (user_id, user_id)
    ).fetchall()
    if rows:
        conn.close()
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": len(rows)}}
    # 진행도: 가장 높은 intimacy 표시
    top = conn.execute(
        "SELECT MAX(intimacy_score) as s FROM relationships "
        "WHERE (agent_a=? AND agent_b LIKE 'agent-persona-%') "
        "   OR (agent_b=? AND agent_a LIKE 'agent-persona-%')",
        (user_id, user_id)
    ).fetchone()
    conn.close()
    s = (top["s"] if top else 0) or 0
    if s >= 50:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"top_intimacy": s, "need": 90}}
    return None


ACHIEVEMENT = Achievement(
    key="bestie",
    title="절친",
    description="한 친구와의 친밀도가 90 이상에 도달.",
    icon="💖",
    check=_check,
)
