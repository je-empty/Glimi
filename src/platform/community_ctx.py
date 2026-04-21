"""플랫폼 안에서 community 전환 + 캐시 invalidation 헬퍼.

구 `scripts/web_dashboard.py` 의 `_COMMUNITY_LOCK` / `_set_active_community` 패턴을
platform 내부용으로 재구현. 여러 community 를 순차 조회할 때 서로 상태 섞이지 않게 보장.
"""
import os
import threading
from contextlib import contextmanager
from typing import Callable, TypeVar

T = TypeVar("T")

_LOCK = threading.Lock()


def _set_active_community(cid: str) -> None:
    """community 전환 + 관련 캐시 전부 무효화."""
    os.environ["GLIMI_COMMUNITY"] = cid
    from src import community as comm
    from src import db as _db
    comm.set_community(cid)
    _db.DB_PATH = None

    try:
        from src.core.profile import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    try:
        from src.bot import _webhook_cache
        _webhook_cache.clear()
    except Exception:
        pass


@contextmanager
def with_community(cid: str):
    """with 블록 안에서 지정 community 컨텍스트 고정. 블록 종료 시 lock 해제."""
    with _LOCK:
        _set_active_community(cid)
        yield


def run_in_community(cid: str, fn: Callable[[], T]) -> T:
    with _LOCK:
        _set_active_community(cid)
        return fn()
