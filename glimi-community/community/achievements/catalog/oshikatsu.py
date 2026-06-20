"""오시카츠 — 버튜버 한 명과 연인 관계 달성 (推し活)."""
from __future__ import annotations

from typing import Optional

from community import db
from community.achievements.base import Achievement
from community.achievements.catalog._shared import get_vtuber_personas


def _check(user_id: str) -> Optional[dict]:
    vtubers = get_vtuber_personas()
    if not vtubers:
        return None
    vtuber_ids = [v["id"] for v in vtubers]
    name_by_id = {v["id"]: v["name"] for v in vtubers}
    placeholders = ",".join("?" * len(vtuber_ids))
    conn = db.get_conn()
    lover = conn.execute(
        f"SELECT agent_a, agent_b FROM relationships WHERE type='연인' AND ("
        f"(agent_a=? AND agent_b IN ({placeholders})) OR "
        f"(agent_b=? AND agent_a IN ({placeholders})))",
        (user_id, *vtuber_ids, user_id, *vtuber_ids)
    ).fetchone()
    conn.close()
    if lover:
        vid = lover["agent_b"] if lover["agent_a"] == user_id else lover["agent_a"]
        vname = name_by_id.get(vid, "?")
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"vtuber": vname}}
    return {"state": "unlocked", "mark_unlocked": True,
            "progress_data": {"vtubers": [v["name"] for v in vtubers]}}


ACHIEVEMENT = Achievement(
    key="oshikatsu",
    title="오시카츠",
    description="버튜버 한 명과 연인 관계 달성 (推し活).",
    icon="📣",
    check=_check,
)
