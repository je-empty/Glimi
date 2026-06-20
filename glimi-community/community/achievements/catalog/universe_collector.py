"""세계관 수집가 — 서로 다른 세계관 친구 3명 이상 보유."""
from __future__ import annotations

from typing import Optional

from community.achievements.base import Achievement
from community.achievements.catalog._shared import get_persona_universes


def _check(user_id: str) -> Optional[dict]:
    universes = get_persona_universes()
    distinct = set(universes.values())
    if len(distinct) >= 3:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"universes": sorted(distinct)}}
    if distinct:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"universes": sorted(distinct), "need": 3}}
    return None


ACHIEVEMENT = Achievement(
    key="universe_collector",
    title="세계관 수집가",
    description="서로 다른 세계관 친구 3명 이상 보유.",
    icon="🌌",
    check=_check,
)
