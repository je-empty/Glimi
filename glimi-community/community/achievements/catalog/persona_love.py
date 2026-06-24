"""연인이 되다 💑 — 친구(페르소나·매니저)와 오너의 상호 사랑."""
from typing import Optional
from community.achievements.base import Achievement
from community.achievements.catalog._shared import check_love_exchange


def check(user_id: str) -> Optional[dict]:
    # 1:1 채널 모두 — dm-* (페르소나 + 매니저 dm-<이름>) + 레거시 mgr-* (구 커뮤니티).
    # 메타 박살된 친구 제외.
    for ch_pat in ("dm-%", "mgr-dashboard", "mgr-creator"):
        result = check_love_exchange(user_id, ch_pat, exclude_meta_breached=True)
        if result:
            return result
    return None


ACHIEVEMENT = Achievement(
    key="persona_love",
    title="연인이 되다 💑",
    description="한 친구와 서로의 마음을 확인하고 연인으로 발전한 순간.",
    icon="💑",
    check=check,
)

