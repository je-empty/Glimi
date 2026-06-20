"""도전과제 자동 디스커버리.

`src/achievements/catalog/` 안의 모든 .py 파일 (이 __init__.py + _* 시작 파일 제외) 을 import 해서
각 모듈의 `ACHIEVEMENT` 를 모음. 파일 추가 = 등록, 파일 삭제 = 미등록.

Convention (각 catalog 파일):
  - 모듈 docstring: 한 줄 도전과제 설명
  - `ACHIEVEMENT: Achievement` — 필수
  - `SUPERVISOR: AchievementSupervisor` — 선택 (실시간 추적 fast-path)
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Optional

from community.achievements.base import Achievement, AchievementSupervisor


def _discover() -> tuple[list[Achievement], list[AchievementSupervisor]]:
    """catalog 디렉토리 모듈 모두 import 하고 ACHIEVEMENT/SUPERVISOR 수집."""
    achs: list[Achievement] = []
    sups: list[AchievementSupervisor] = []
    for finder, name, _ in pkgutil.iter_modules(__path__):
        if name.startswith("_"):
            continue  # private/util
        try:
            mod = importlib.import_module(f"{__name__}.{name}")
        except Exception as e:
            print(f"[achievements/catalog] {name} import 실패: {e}")
            continue
        ach = getattr(mod, "ACHIEVEMENT", None)
        if isinstance(ach, Achievement):
            achs.append(ach)
        sup = getattr(mod, "SUPERVISOR", None)
        if isinstance(sup, AchievementSupervisor):
            # supervisor.key 가 비어있으면 catalog 파일명 (= achievement key) 으로 채움
            if not sup.key and ach:
                sup.key = ach.key
            sups.append(sup)
    return achs, sups


# import time 에 1회 디스커버. 이후 ACHIEVEMENTS / SUPERVISORS 는 정적.
ACHIEVEMENTS, SUPERVISORS = _discover()


def get_by_key(key: str) -> Optional[Achievement]:
    for a in ACHIEVEMENTS:
        if a.key == key:
            return a
    return None
