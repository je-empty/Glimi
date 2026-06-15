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


# ── _build_activity_digest (최근 활동 요약) — 동일 클래스 버그 ──────────────
#
# datetime.now() (naive LOCAL) - fromisoformat(last_active) (AWARE 면) → TypeError.
# 이 크래시는 except 로 swallow 되어 mins=9999 → 최근 채널이 "활동 없음"으로 누락된다
# (naive last_active 라도 now()=로컬 vs UTC 불일치로 경과시간이 tz 오프셋만큼 틀어짐).
# fix: now=datetime.now(timezone.utc), last 가 naive 면 UTC 로 정규화.


class _FakeDigestStore:
    """_build_activity_digest 가 호출하는 메서드만 구현."""

    def __init__(self, overview, recent=None, agents=None):
        self._overview = overview
        self._recent = recent or {}
        self._agents = agents or []

    def get_channel_overview(self):
        return self._overview

    def get_recent_messages(self, channel, limit=10):
        return self._recent.get(channel, [])

    def list_agents(self, agent_type=None):
        return self._agents


class _FakeOwner:
    def name(self):
        return "주인"

    def id(self):
        return "owner-1"

    def display_name(self):
        return "주인"

    def call_name(self):
        return "주인"

    def profile(self):
        return {}


@pytest.fixture
def restore_owner():
    saved = runtime._owner
    yield
    runtime.set_owner(saved)


def _digest_overview(channel, delta, iso_factory, msg_count=3):
    return [{"channel": channel, "last_active": iso_factory(delta), "msg_count": msg_count}]


@pytest.mark.parametrize("iso_factory", [_aware_iso, _naive_iso])
def test_activity_digest_recent_channel_is_active(restore_store, restore_owner, iso_factory):
    """5분 전 채널은 '[최근 활동]'에 떠야 한다.

    AWARE last_active 면 미수정 코드는 naive-now 와의 연산이 TypeError →
    except 로 swallow → mins=9999 → active 누락. 즉 이 단언이 fix 를 검증한다.
    """
    runtime.set_owner(_FakeOwner())
    runtime.set_store(
        _FakeDigestStore(
            _digest_overview("dm-nova", timedelta(minutes=5), iso_factory),
            recent={"dm-nova": [{"speaker": "owner-1", "message": "안녕 반가워"}]},
        )
    )
    out = AgentRuntime()._build_activity_digest()
    assert "[최근 활동]" in out
    assert "dm-nova" in out


@pytest.mark.parametrize("iso_factory", [_aware_iso, _naive_iso])
def test_activity_digest_no_offset_naive_aware_typeerror(restore_store, restore_owner, iso_factory):
    """혼합 naive/aware 연산이 TypeError 로 전파되지 않아야 한다."""
    runtime.set_owner(_FakeOwner())
    runtime.set_store(_FakeDigestStore(_digest_overview("c", timedelta(hours=2), iso_factory)))
    try:
        out = AgentRuntime()._build_activity_digest()
    except TypeError as e:  # pragma: no cover - 회귀 시에만 도달
        if "offset-naive and offset-aware" in str(e):
            pytest.fail(f"회귀: activity digest 혼합 naive/aware 크래시 — {e}")
        raise
    assert isinstance(out, str)
