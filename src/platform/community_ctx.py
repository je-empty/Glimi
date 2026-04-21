"""커뮤니티 전환 헬퍼 — dashboard.context 를 얇게 감쌈.

하나의 전역 lock 을 공유해야 함 (두 lock 이 같은 global state 건드리면 race).
실제 구현은 `src.platform.dashboard.context` 에 집중.
"""
from contextlib import contextmanager
from typing import Callable, TypeVar

from .dashboard.context import (
    _COMMUNITY_LOCK,
    _set_active_community,
)

T = TypeVar("T")


@contextmanager
def with_community(cid: str):
    """with 블록 안에서 지정 community 컨텍스트 고정."""
    with _COMMUNITY_LOCK:
        _set_active_community(cid)
        yield


def run_in_community(cid: str, fn: Callable[[], T]) -> T:
    with _COMMUNITY_LOCK:
        _set_active_community(cid)
        return fn()
