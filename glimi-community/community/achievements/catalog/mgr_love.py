"""직함 내려놓기 💝 — 매니저(서유나/윤하나)와 오너의 상호 사랑."""
from typing import Optional
from community.achievements.base import Achievement
from community.achievements.catalog._shared import check_love_exchange


def check(user_id: str) -> Optional[dict]:
    for ch_pat in ("mgr-dashboard", "mgr-creator"):
        result = check_love_exchange(user_id, ch_pat)
        if result:
            return result
    return None


ACHIEVEMENT = Achievement(
    key="mgr_love",
    title="직함 내려놓기 💝",
    description="매니저가 직함을 내려놓고 오너와 사람 대 사람의 사랑을 나눈 순간.",
    icon="💝",
    check=check,
)
