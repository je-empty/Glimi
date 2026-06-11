"""하코오시 — 버튜버 5명 이상과 연인 관계 달성 (箱推し)."""
from __future__ import annotations

from typing import Optional

from src import db
from src.achievements.base import Achievement
from src.achievements.catalog._shared import get_vtuber_personas


def _check(user_id: str) -> Optional[dict]:
    vtubers = get_vtuber_personas()
    if not vtubers:
        return None
    vtuber_ids = [v["id"] for v in vtubers]
    name_by_id = {v["id"]: v["name"] for v in vtubers}
    placeholders = ",".join("?" * len(vtuber_ids))
    conn = db.get_conn()
    lovers = conn.execute(
        f"SELECT agent_a, agent_b FROM relationships WHERE type='연인' AND ("
        f"(agent_a=? AND agent_b IN ({placeholders})) OR "
        f"(agent_b=? AND agent_a IN ({placeholders})))",
        (user_id, *vtuber_ids, user_id, *vtuber_ids)
    ).fetchall()
    conn.close()
    lover_names = []
    for r in lovers:
        vid = r["agent_b"] if r["agent_a"] == user_id else r["agent_a"]
        if vid in name_by_id:
            lover_names.append(name_by_id[vid])
    cnt = len(set(lover_names))
    if cnt >= 5:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt, "vtubers": sorted(set(lover_names))}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": 5, "vtubers": sorted(set(lover_names))}}
    return None


ACHIEVEMENT = Achievement(
    key="hakooshi",
    title="하코오시",
    description="버튜버 5명 이상과 연인 관계 달성 (箱推し).",
    icon="🎀",
    check=_check,
)
