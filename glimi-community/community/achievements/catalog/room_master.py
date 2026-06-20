"""방 주인 🏠 — 단톡방 5+ 생성 (events.event_type='단톡방생성|비밀톡방생성')."""
from typing import Optional
from community.achievements.base import Achievement
from community.achievements.catalog._shared import check_event_count


def check(user_id: str) -> Optional[dict]:
    return check_event_count(["단톡방생성", "비밀톡방생성"], 5)


ACHIEVEMENT = Achievement(
    key="room_master",
    title="방 주인",
    description="다양한 단톡방 5개 이상 만들기.",
    icon="🏠",
    check=check,
)
