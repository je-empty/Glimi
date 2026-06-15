"""glimi/memory.py 타임존 회귀 테스트.

버그: get_memory_context 경로의 헬퍼(_format_age/_is_stale/_days_since)가
저장된 ISO 타임스탬프를 datetime.fromisoformat() 으로 파싱(+00:00 이 붙으면
tz-AWARE) 한 뒤 naive 한 datetime.utcnow() 와 빼면서
"can't subtract offset-naive and offset-aware datetimes" TypeError 로 크래시.

fix: _parse_iso 가 항상 tz-aware(UTC) 를 반환하고, 헬퍼들이
datetime.now(timezone.utc) 를 사용하도록 정규화.

실행: PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_memory_tz.py -q
"""
from datetime import datetime, timedelta, timezone

import pytest

from glimi.memory import _days_since, _format_age, _is_stale, _parse_iso


# ── _parse_iso: 항상 tz-aware(UTC) 반환 ──────────────────────────────

def test_parse_iso_aware_input_stays_aware():
    """+00:00 이 붙은 AWARE ISO → tz-aware UTC 유지."""
    dt = _parse_iso("2026-06-15T12:00:00+00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_parse_iso_naive_input_normalized_to_utc():
    """tz 정보 없는 NAIVE ISO → UTC 로 간주하여 tz-aware 로 정규화."""
    dt = _parse_iso("2026-06-15 12:00:00")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_parse_iso_none_and_garbage():
    """기존 None/except 처리 유지."""
    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not-a-date") is None


# ── 헬퍼들: AWARE / NAIVE ISO 둘 다 크래시 없이 동작 ─────────────────

def _aware_iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).isoformat()


def _naive_iso(delta: timedelta) -> str:
    # SQLite CURRENT_TIMESTAMP 스타일 (naive, UTC 기준)
    return (datetime.now(timezone.utc) - delta).replace(tzinfo=None).isoformat(sep=" ")


def test_format_age_aware_does_not_raise():
    """AWARE UTC ISO 입력 — 원본(미수정) 코드라면 여기서 크래시."""
    out = _format_age(_aware_iso(timedelta(hours=2)))
    assert out  # 비어있지 않음
    assert "시간" in out


def test_format_age_naive_input():
    out = _format_age(_naive_iso(timedelta(minutes=30)))
    assert "분" in out


def test_is_stale_aware_does_not_raise():
    old = _aware_iso(timedelta(hours=48))
    fresh = _aware_iso(timedelta(minutes=5))
    assert _is_stale(old, hours=24) is True
    assert _is_stale(fresh, hours=24) is False


def test_is_stale_naive_input():
    old = _naive_iso(timedelta(hours=48))
    assert _is_stale(old, hours=24) is True


def test_days_since_aware_does_not_raise():
    d = _days_since(_aware_iso(timedelta(days=3)))
    assert 2.5 <= d <= 3.5


def test_days_since_naive_input():
    d = _days_since(_naive_iso(timedelta(days=1)))
    assert 0.5 <= d <= 1.5


# ── 직접 재현: offset-naive/aware 혼합 TypeError 가 없음을 단언 ────────

@pytest.mark.parametrize("iso", [
    "2026-06-15T12:00:00+00:00",   # AWARE (마이그레이션 이후 행)
    "2026-06-15 12:00:00",          # NAIVE (SQLite CURRENT_TIMESTAMP)
])
def test_no_offset_naive_aware_typeerror(iso):
    """원본 버그 직접 재현: 혼합 datetime 연산에서 TypeError 가 나지 않아야 함."""
    try:
        _format_age(iso)
        _is_stale(iso, hours=24)
        _days_since(iso)
    except TypeError as e:  # pragma: no cover - 회귀 시에만 도달
        if "offset-naive and offset-aware" in str(e):
            pytest.fail(f"회귀: 혼합 naive/aware datetime 크래시 재발 — {e}")
        raise
