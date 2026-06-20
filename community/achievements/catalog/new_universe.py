"""이세계 탐험 — 첫 번째 세계관에 발을 디뎠다."""
from __future__ import annotations

from typing import Optional

from community.achievements.base import Achievement
from community.achievements.catalog._shared import get_persona_universes


def _check(user_id: str) -> Optional[dict]:
    universes = get_persona_universes()
    distinct = set(universes.values())
    if distinct:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"universes": sorted(distinct)}}
    return None


ACHIEVEMENT = Achievement(
    key="new_universe",
    title="이세계 탐험",
    description="첫 번째 세계관에 발을 디뎠다.",
    icon="🌠",
    check=_check,
)
