# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
LLM 백엔드 선택 + 편의 함수 파사드.

사용:
    from glimi.llm import generate
    resp = generate(
        system="너는 유나",
        user="안녕",
        model="claude-sonnet-4-6",
        agent_type="mgr",
        cacheable_system=True,
    )
    print(resp.text)

백엔드 선택 우선순위:
  1) 호출자가 `backend=` 명시
  2) `GLIMI_LLM_AGENT_MAP` env (JSON) 의 agent_type 매핑
  3) `GLIMI_LLM_BACKEND` env (전역)
  4) SDK 기본 시도 (ANTHROPIC_API_KEY 있으면 SDK, 없으면 CLI 폴백)
  5) CLI
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from .base import LLMBackend, LLMResponse
from .claude_cli import ClaudeCLIBackend, find_claude
from .anthropic_sdk import AnthropicSDKBackend
from . import pricing


# 싱글톤 인스턴스
_BACKENDS: dict[str, LLMBackend] = {}


# ── usage 회계 sink (Path B 중앙 집결점) ──
# facade 는 store 를 모른다. 앱 edge (set_store 부르는 곳) 에서 set_usage_sink(store) 등록.
# 미등록 (zero-config harness/test) → record = no-op (기존 동작 보존).
_usage_sink = None


def set_usage_sink(store) -> None:
    """LLM 사용량 기록 sink 등록 (KernelStore 호환 — record_usage 메서드 보유).

    미호출 시 모든 usage 기록이 no-op (standalone / 테스트). 앱이 set_store() 와 함께
    호출하면 generate() 호출마다 실측 토큰 + 비용이 usage_records 에 1행 적립된다.
    """
    global _usage_sink
    _usage_sink = store


def _record_usage(resp: LLMResponse, *, backend_name: str, agent_type: str,
                  latency_ms: int) -> None:
    """LLMResponse 의 실측 usage + 추정 비용을 sink 에 1행 기록.

    SDK 경로 = 실측 토큰 (estimated=0, 정확한 $). ollama/echo 등 로컬 = 토큰은 실측이지만
    가격표 부재 → $0. 에러 응답은 기록하지 않는다. 회계가 생성을 절대 깨지 않게 try/except.
    """
    try:
        if _usage_sink is None or resp is None or resp.error:
            return
        model = resp.model or ""
        est = pricing.estimate_cost(
            model,
            resp.input_tokens or 0,
            resp.output_tokens or 0,
            resp.cache_read_tokens or 0,
            resp.cache_write_tokens or 0,
        )
        _usage_sink.record_usage(
            agent_type=agent_type or None,
            model=model or None,
            backend=backend_name or None,
            input_tokens=resp.input_tokens or 0,
            output_tokens=resp.output_tokens or 0,
            cache_read_tokens=resp.cache_read_tokens or 0,
            cache_write_tokens=resp.cache_write_tokens or 0,
            est_cost=est,
            estimated=False,  # facade(SDK/ollama) 는 실측 토큰
            latency_ms=latency_ms,
        )
    except Exception:
        pass


def _get_backend_instance(name: str) -> Optional[LLMBackend]:
    if name in _BACKENDS:
        return _BACKENDS[name]
    if name == "claude_cli":
        b = ClaudeCLIBackend()
    elif name == "anthropic_sdk":
        b = AnthropicSDKBackend()
    elif name == "ollama":
        from .ollama import OllamaBackend
        b = OllamaBackend()
    elif name in ("grok_cli", "grok"):
        from .grok_cli import GrokCLIBackend
        b = GrokCLIBackend()
    elif name == "echo":
        # 오프라인·무의존 백엔드. 자동 선택 안 됨 — backend="echo" 또는
        # GLIMI_LLM_BACKEND=echo 로 명시할 때만 (quick-start / 테스트용).
        from .echo import EchoBackend
        b = EchoBackend()
    else:
        return None
    _BACKENDS[name] = b
    return b


def _agent_type_backend(agent_type: str) -> Optional[str]:
    raw = os.environ.get("GLIMI_LLM_AGENT_MAP", "").strip()
    if not raw:
        return None
    try:
        m = json.loads(raw)
        if isinstance(m, dict):
            v = m.get(agent_type) or m.get("_default")
            return str(v) if v else None
    except Exception:
        pass
    return None


# Claude (paid) backend names — the budget guard only diverts these.
_CLAUDE_BACKENDS = ("claude_cli", "anthropic_sdk")


def _budget_diverted_backend(b: LLMBackend, agent_type: str) -> Optional[LLMBackend]:
    """Guard point 2 (background facade). If ``b`` is a Claude backend and the
    monthly cap is exceeded, return a non-Claude replacement: ollama when usable,
    else None (caller emits a capped empty LLMResponse + records was_blocked).
    Returns ``b`` unchanged (the same instance) when within budget / not Claude.

    Degrade open: any guard error → keep ``b`` (never block on a guard hiccup)."""
    if b is None or b.name not in _CLAUDE_BACKENDS:
        return b
    try:
        from .. import budget
        from ..runtime import community_id
        if budget.allow_claude(community_id()):
            return b
    except Exception:
        return b  # guard failure must never block
    # over cap — prefer local ollama, else signal "no fallback" with None
    try:
        oll = _get_backend_instance("ollama")
        if oll and oll.available():
            return oll
    except Exception:
        pass
    return None


def _record_facade_blocked(*, model: str, agent_type: str) -> None:
    """Record a budget-blocked facade call (was_blocked=True, backend='capped',
    est_cost=0). no-op when no usage sink. Never raises."""
    try:
        if _usage_sink is None:
            return
        from ..runtime import community_id
        _usage_sink.record_usage(
            community=community_id(),
            agent_type=agent_type or None,
            model=model or None,
            backend="capped",
            est_cost=0.0,
            estimated=True,
            was_blocked=True,
        )
    except Exception:
        pass


def _capped_response(model: str) -> LLMResponse:
    """Empty LLMResponse for a budget-capped facade call with no local fallback.
    Empty text — memory._call_claude already treats empty as a no-op drop."""
    return LLMResponse(text="", model=model or "", error="budget_capped")


def _select_backend(agent_type: str = "", override: str = "") -> LLMBackend:
    """백엔드 선택 — 우선순위에 따라 결정."""
    # 1) 명시적 override
    if override:
        b = _get_backend_instance(override)
        if b and b.available():
            return b

    # 2) agent_type 매핑
    tmap = _agent_type_backend(agent_type)
    if tmap:
        b = _get_backend_instance(tmap)
        if b and b.available():
            return b

    # 3) 전역 env
    glob = os.environ.get("GLIMI_LLM_BACKEND", "").strip()
    if glob:
        b = _get_backend_instance(glob)
        if b and b.available():
            return b

    # 4) SDK 자동 (API key 있으면)
    sdk = _get_backend_instance("anthropic_sdk")
    if sdk and sdk.available():
        return sdk

    # 5) CLI fallback
    cli = _get_backend_instance("claude_cli")
    if cli and cli.available():
        return cli

    # 무조건 CLI 인스턴스 반환 (error response 내기 위해)
    return ClaudeCLIBackend()


def generate(
    *,
    system: str,
    user: str,
    model: str,
    agent_type: str = "",
    backend: str = "",
    max_tokens: int = 2048,
    timeout: int = 60,
    cacheable_system: bool = False,
    **kwargs,
) -> LLMResponse:
    """단일 완성 생성. LLMResponse 반환 (text / usage / error)."""
    b = _select_backend(agent_type=agent_type, override=backend)
    # Budget guard (point 2): Claude 백엔드 + 월 예산 초과 → ollama 강제, 없으면 capped.
    diverted = _budget_diverted_backend(b, agent_type)
    if diverted is None:
        _record_facade_blocked(model=model, agent_type=agent_type)
        return _capped_response(model)
    b = diverted
    _t0 = time.monotonic()
    resp = b.generate(
        system=system, user=user, model=model,
        max_tokens=max_tokens, timeout=timeout,
        cacheable_system=cacheable_system, **kwargs,
    )
    _record_usage(resp, backend_name=b.name, agent_type=agent_type,
                  latency_ms=int((time.monotonic() - _t0) * 1000))
    return resp


def stream_lines(
    *,
    system: str,
    user: str,
    model: str,
    agent_type: str = "",
    backend: str = "",
    max_tokens: int = 2048,
    timeout: int = 120,
    cacheable_system: bool = False,
    **kwargs,
):
    """라인 단위 스트림. CLI 는 stdout 실시간 read, SDK 는 완성 후 라인 split."""
    b = _select_backend(agent_type=agent_type, override=backend)
    # Budget guard (point 2): Claude 백엔드 + 월 예산 초과 → ollama 강제, 없으면 무출력.
    diverted = _budget_diverted_backend(b, agent_type)
    if diverted is None:
        _record_facade_blocked(model=model, agent_type=agent_type)
        return  # capped + no local fallback → empty stream
    b = diverted
    yield from b.stream_lines(
        system=system, user=user, model=model,
        max_tokens=max_tokens, timeout=timeout,
        cacheable_system=cacheable_system, **kwargs,
    )


def current_backend_name(agent_type: str = "") -> str:
    """진단용 — 현재 선택될 백엔드 이름."""
    return _select_backend(agent_type=agent_type).name


__all__ = [
    "generate",
    "stream_lines",
    "current_backend_name",
    "set_usage_sink",
    "find_claude",
    "LLMResponse",
    "LLMBackend",
]
