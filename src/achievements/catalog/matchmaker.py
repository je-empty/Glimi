"""소개팅 주선자 💌 — dm_request 이벤트 10+ (친구끼리 dm 연결)."""
from typing import Optional
from src.achievements.base import Achievement
from src.achievements.catalog._shared import check_event_count


def check(user_id: str) -> Optional[dict]:
    return check_event_count(["dm_request"], 10)


ACHIEVEMENT = Achievement(
    key="matchmaker",
    title="소개팅 주선자",
    description="친구끼리 DM 으로 연결한 적 10번.",
    icon="💌",
    check=check,
)
