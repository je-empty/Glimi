"""
LLM 백엔드 선택 + 편의 함수 파사드.

사용:
    from src.llm import generate
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
from typing import Optional

from .base import LLMBackend, LLMResponse
from .claude_cli import ClaudeCLIBackend
from .anthropic_sdk import AnthropicSDKBackend


# 싱글톤 인스턴스
_BACKENDS: dict[str, LLMBackend] = {}


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
    return b.generate(
        system=system, user=user, model=model,
        max_tokens=max_tokens, timeout=timeout,
        cacheable_system=cacheable_system, **kwargs,
    )


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
    "LLMResponse",
    "LLMBackend",
]
