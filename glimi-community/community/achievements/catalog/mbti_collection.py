"""MBTI 콜렉션 — 서로 다른 MBTI 친구 4명 이상 보유."""
from __future__ import annotations

from typing import Optional

from community import db
from community.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT DISTINCT mbti FROM agents WHERE type='persona' AND status='active' "
        "AND mbti IS NOT NULL AND mbti != ''"
    ).fetchall()
    conn.close()
    distinct = {r["mbti"] for r in rows if r["mbti"]}
    if len(distinct) >= 4:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"mbtis": sorted(distinct)}}
    if distinct:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"mbtis": sorted(distinct), "need": 4}}
    return None


ACHIEVEMENT = Achievement(
    key="mbti_collection",
    title="MBTI 콜렉션",
    description="서로 다른 MBTI 친구 4명 이상 보유.",
    icon="🎯",
    check=_check,
)
