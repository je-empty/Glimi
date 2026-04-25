"""도전과제 정의 — 후방호환 shim.

실제 정의는 `src/achievements/catalog/<key>.py` 개별 파일. 이 모듈은:
1. catalog 의 `ACHIEVEMENTS` 목록을 그대로 re-export
2. `Achievement` 데이터클래스를 base 에서 re-export (외부 임포터 호환)
3. `get_by_key` 헬퍼 re-export

새 도전과제 추가 시: `catalog/<new_key>.py` 만 만들면 끝. 이 파일은 안 건드림.
"""
from __future__ import annotations

from src.achievements.base import Achievement, AchievementSupervisor
from src.achievements.catalog import ACHIEVEMENTS, SUPERVISORS, get_by_key


__all__ = ["Achievement", "AchievementSupervisor", "ACHIEVEMENTS", "SUPERVISORS", "get_by_key"]
