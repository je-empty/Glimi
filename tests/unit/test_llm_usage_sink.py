"""glimi.llm.generate 의 Path B usage sink 검증 (중앙 회계 집결점).

검증:
  - set_usage_sink 등록 시 generate() 가 sink.record_usage 를 1회 호출 (실측 토큰/모델/backend)
  - 미등록 (zero-config harness/test) 이면 no-op — generate 동작 그대로
  - 에러 응답은 기록하지 않음
  - SDK 모델은 가격 적용, 로컬/echo 는 $0 (estimated=False — 실측 토큰)

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_llm_usage_sink.py -q
"""
from __future__ import annotations

import pytest

from glimi import llm
from glimi.llm.base import LLMResponse


class _Sink:
    def __init__(self):
        self.rows: list[dict] = []

    def record_usage(self, **kw):
        self.rows.append(kw)
        return len(self.rows)


@pytest.fixture()
def sink():
    saved = llm._usage_sink
    s = _Sink()
    llm.set_usage_sink(s)
    try:
        yield s
    finally:
        llm.set_usage_sink(saved)


@pytest.fixture()
def no_sink():
    saved = llm._usage_sink
    llm.set_usage_sink(None)
    try:
        yield
    finally:
        llm.set_usage_sink(saved)


def test_echo_generate_records_zero_cost_real_tokens(sink):
    resp = llm.generate(system="You are Nova", user="hi", model="echo",
                        agent_type="persona", backend="echo")
    assert resp.text
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row["backend"] == "echo"
    assert row["agent_type"] == "persona"
    assert row["est_cost"] == 0.0       # echo not in price table → free
    assert row["estimated"] is False    # facade = real tokens (echo returns 0)
    assert "latency_ms" in row


def test_no_sink_is_noop(no_sink):
    resp = llm.generate(system="s", user="u", model="echo",
                        agent_type="persona", backend="echo")
    assert resp.text  # generation unaffected with no sink registered


def test_record_helper_prices_sdk_model(sink):
    """A real-usage SDK-shaped LLMResponse prices via the table (estimated=0)."""
    resp = LLMResponse(text="ok", model="claude-haiku-4-5",
                       input_tokens=1_000_000, output_tokens=0)
    llm._record_usage(resp, backend_name="anthropic_sdk",
                      agent_type="memory_extract", latency_ms=120)
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row["model"] == "claude-haiku-4-5"
    # haiku-4-5 = $1 / 1M input.
    assert abs(row["est_cost"] - 1.0) < 1e-9
    assert row["estimated"] is False
    assert row["input_tokens"] == 1_000_000


def test_error_response_not_recorded(sink):
    resp = LLMResponse(text="", model="claude-haiku-4-5",
                       error="anthropic_sdk: boom")
    llm._record_usage(resp, backend_name="anthropic_sdk",
                      agent_type="judge", latency_ms=50)
    assert sink.rows == []
