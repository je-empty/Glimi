"""환각 차단 — 감시 에이전트가 환각 발화를 차단한 적 있다 (디버그)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from community.achievements.base import Achievement


def _check(user_id: str) -> Optional[dict]:
    """system 로그에 환각 필터 발동 흔적 있음. log 파일 스캔.

    구현 한계: log 파일 위치는 community_dir/logs/ — runtime 마다 다를 수 있어
    완벽 추적은 어려움. system 로그 추정 위치 스캔만 시도, 실패 시 None.
    """
    try:
        # Mac/root 양쪽 호환 — get_log_dir 우선, 없으면 fallback
        try:
            from community.community import get_log_dir
            logs_dir = Path(get_log_dir())
        except ImportError:
            from community.community import get_community_dir
            logs_dir = get_community_dir() / "logs"
        if not logs_dir.exists():
            return None
        cnt = 0
        for fp in logs_dir.glob("*.log"):
            try:
                with open(fp, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "환각 필터" in line and "차단" in line:
                            cnt += 1
                            if cnt >= 1:
                                break
            except Exception:
                continue
            if cnt >= 1:
                break
        if cnt >= 1:
            return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                    "progress_data": {"count": cnt}}
    except Exception:
        pass
    return None


ACHIEVEMENT = Achievement(
    key="reality_check",
    title="환각 차단",
    description="감시 에이전트가 환각 발화를 차단한 적 있다 (디버그).",
    icon="🌙",
    check=_check,
)
