"""dispatcher.run_single 의 tool-call 관측 choke-point 검증.

검증:
  - store 주입 시 run_single 이 record_tool_call 을 정확히 1회 호출 (name/args/ok/latency)
  - 실패한 tool 도 ok=0 + error preview 로 기록
  - store 미주입 (standalone/harness) 이면 no-op (예외 없이 실행만 정상)
  - 기록 자체가 실패해도 (record_tool_call 이 throw) tool 결과는 영향 없음

run_single 은 glimi.runtime 모듈 전역 _store 를 매 호출 읽으므로, 모듈 속성을
직접 set/restore 한다 (set_store 가 재대입하는 동일 글로벌).

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_tool_call_capture.py -q
"""
from __future__ import annotations

import asyncio

import pytest

from glimi.tools import registry
from glimi.tools.registry import ToolSpec
from glimi.tools.parser import ToolCall
from glimi.tools.dispatcher import run_single, ToolContext
from glimi import runtime as _rt


class _RecordingStore:
    """관측만 가로채는 최소 store 더블 — record_tool_call 호출 캡처."""

    def __init__(self, *, raise_on_record: bool = False):
        self.calls: list[dict] = []
        self._raise = raise_on_record

    def record_tool_call(self, **kw):
        if self._raise:
            raise RuntimeError("store boom")
        self.calls.append(kw)
        return len(self.calls)


@pytest.fixture()
def fake_store():
    """glimi.runtime._store 를 더블로 교체 후 복원."""
    saved = _rt._store
    store = _RecordingStore()
    _rt._store = store
    try:
        yield store
    finally:
        _rt._store = saved


@pytest.fixture()
def no_store():
    """glimi.runtime._store 를 None 으로 (standalone) 후 복원."""
    saved = _rt._store
    _rt._store = None
    try:
        yield
    finally:
        _rt._store = saved


def _ctx(agent_type="mgr"):
    return ToolContext(
        caller_agent_id="agent-1", caller_agent_type=agent_type,
        channel_name="mgr-log",
    )


def _register(name, handler, applies=("mgr",), params=None):
    spec = ToolSpec(
        name=name, description="d",
        params=params or {"x": {"type": "str", "required": True}},
        category="management", applies_to=frozenset(applies),
    )
    spec.handler = handler
    registry.TOOLS[name] = spec
    return name


def test_capture_records_one_row_on_success(fake_store):
    name = _register("__cap_ok__", lambda args, ctx: {"echo": args["x"]})
    try:
        r = asyncio.run(run_single(ToolCall(id="1", name=name, args={"x": "hi"}), _ctx()))
        assert r.ok is True
    finally:
        registry.TOOLS.pop(name, None)
    assert len(fake_store.calls) == 1
    rec = fake_store.calls[0]
    assert rec["tool_name"] == name
    assert rec["ok"] is True
    assert rec["agent_id"] == "agent-1"
    assert rec["agent_type"] == "mgr"
    assert rec["channel"] == "mgr-log"
    assert '"x": "hi"' in rec["args_json"] or '"x":"hi"' in rec["args_json"]
    assert isinstance(rec["latency_ms"], int) and rec["latency_ms"] >= 0
    assert "echo" in rec["result_preview"]


def test_capture_records_failure_with_error_preview(fake_store):
    # unknown tool → fail() path; still recorded with ok=False.
    r = asyncio.run(run_single(ToolCall(id="2", name="__no_such_tool__", args={}), _ctx()))
    assert r.ok is False
    assert len(fake_store.calls) == 1
    rec = fake_store.calls[0]
    assert rec["ok"] is False
    assert rec["tool_name"] == "__no_such_tool__"
    assert "unknown tool" in (rec["result_preview"] or "")


def test_no_store_is_noop_and_tool_still_runs(no_store):
    name = _register("__cap_nostore__", lambda args, ctx: {"echo": args["x"]})
    try:
        r = asyncio.run(run_single(ToolCall(id="3", name=name, args={"x": "yo"}), _ctx()))
        assert r.ok is True and r.data == {"echo": "yo"}
    finally:
        registry.TOOLS.pop(name, None)


def test_recording_failure_never_breaks_tool_execution():
    saved = _rt._store
    _rt._store = _RecordingStore(raise_on_record=True)
    name = _register("__cap_raise__", lambda args, ctx: {"echo": args["x"]})
    try:
        # record_tool_call throws internally, but run_single must still return ok.
        r = asyncio.run(run_single(ToolCall(id="4", name=name, args={"x": "z"}), _ctx()))
        assert r.ok is True and r.data == {"echo": "z"}
    finally:
        registry.TOOLS.pop(name, None)
        _rt._store = saved
