"""glimi/runtime.py 타임존 회귀 테스트 (dm_request 도구 이력 빌더).

버그: AgentRuntime._build_recent_tool_history 가 저장된 이벤트 timestamp 를
datetime.fromisoformat() 으로 파싱(+00:00 이 붙으면 tz-AWARE) 한 뒤
naive 한 datetime.utcnow() 와 빼면서
"can't subtract offset-naive and offset-aware datetimes" TypeError 로 크래시.
PR #7(memory.py)과 동일한 클래스의 버그.

fix: now 를 datetime.now(timezone.utc) (aware) 로 만들고, 파싱한 ts 가
naive 면 UTC 로 간주해 aware 로 정규화한 뒤 빼도록 변경.

실행: PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_runtime_tz.py -q
"""
from datetime import datetime, timedelta, timezone

import pytest

import glimi.runtime as runtime
from glimi.runtime import AgentRuntime


class _FakeStore:
    """get_recent_events 만 구현하는 최소 가짜 스토어.

    _build_recent_tool_history 는 _store.get_recent_events 만 호출하므로
    그 한 메서드만 채우면 빌더를 단독 실행할 수 있다.
    """

    def __init__(self, rows):
        self._rows = rows

    def get_recent_events(self, agent_id, event_types, window_sec, limit=8):
        return self._rows


def _event_row(timestamp: str) -> dict:
    return {
        "timestamp": timestamp,
        "event_type": "dm_request",
        "participants": "agent-1,agent-2",
        "description": "테스트 요청",
    }


@pytest.fixture
def restore_store():
    """주입한 전역 _store 를 원복."""
    saved = runtime._store
    yield
    runtime.set_store(saved)


def _aware_iso(delta: timedelta) -> str:
    """마이그레이션 이후 행 스타일 (tz-aware, +00:00)."""
    return (datetime.now(timezone.utc) - delta).isoformat()


def _naive_iso(delta: timedelta) -> str:
    """SQLite CURRENT_TIMESTAMP 스타일 (naive, UTC 기준, 공백 구분)."""
    return (datetime.now(timezone.utc) - delta).replace(tzinfo=None).isoformat(sep=" ")


def test_aware_timestamp_does_not_raise(restore_store):
    """AWARE UTC ISO 이벤트 — 원본(미수정) 코드라면 TypeError 로 크래시.

    빌더가 예외 없이 elapsed 마커("분 전"/"방금 전")를 담은 문자열을 반환해야 함.
    """
    runtime.set_store(_FakeStore([_event_row(_aware_iso(timedelta(minutes=42)))]))
    out = AgentRuntime()._build_recent_tool_history("agent-1")
    assert isinstance(out, str)
    assert out  # 비어있지 않음 — "최근" fallback 으로 빠지지 않았음
    assert ("분 전" in out) or ("방금 전" in out)


def test_naive_timestamp_still_works(restore_store):
    """NAIVE ISO 이벤트(레거시 행)도 그대로 동작."""
    runtime.set_store(_FakeStore([_event_row(_naive_iso(timedelta(minutes=10)))]))
    out = AgentRuntime()._build_recent_tool_history("agent-1")
    assert ("분 전" in out) or ("방금 전" in out)


@pytest.mark.parametrize("iso_factory", [_aware_iso, _naive_iso])
def test_no_offset_naive_aware_typeerror(restore_store, iso_factory):
    """원본 버그 직접 재현: 혼합 datetime 연산에서 TypeError 가 나지 않아야 함."""
    runtime.set_store(_FakeStore([_event_row(iso_factory(timedelta(hours=3)))]))
    try:
        AgentRuntime()._build_recent_tool_history("agent-1")
    except TypeError as e:  # pragma: no cover - 회귀 시에만 도달
        if "offset-naive and offset-aware" in str(e):
            pytest.fail(f"회귀: 혼합 naive/aware datetime 크래시 재발 — {e}")
        raise


def test_elapsed_marker_recent(restore_store):
    """1분 미만 경과 → '방금 전' 마커."""
    runtime.set_store(_FakeStore([_event_row(_aware_iso(timedelta(seconds=20)))]))
    out = AgentRuntime()._build_recent_tool_history("agent-1")
    assert "방금 전" in out


def test_empty_rows_returns_empty(restore_store):
    """이벤트 없으면 빈 문자열 (기존 동작 유지)."""
    runtime.set_store(_FakeStore([]))
    assert AgentRuntime()._build_recent_tool_history("agent-1") == ""
