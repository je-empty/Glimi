"""연인이 되다 💑 — persona 친구와 오너의 상호 사랑 (메타 박살된 친구 제외)."""
from typing import Optional
from src.achievements.base import Achievement
from src.achievements.catalog._shared import check_love_exchange


def check(user_id: str) -> Optional[dict]:
    return check_love_exchange(user_id, "dm-%", exclude_meta_breached=True)


ACHIEVEMENT = Achievement(
    key="persona_love",
    title="연인이 되다 💑",
    description="한 친구와 서로의 마음을 확인하고 연인으로 발전한 순간.",
    icon="💑",
    check=check,
)
