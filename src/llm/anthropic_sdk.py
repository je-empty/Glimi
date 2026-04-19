"""
Anthropic SDK 백엔드 — 직접 API 호출 + prompt caching.

환경변수:
  ANTHROPIC_API_KEY — 필수

prompt caching:
  `cacheable_system=True` 일 때 system block 에 `cache_control={"type":"ephemeral"}` 태깅.
  기본 TTL 5분. system prompt + tool reference 가 대부분의 에이전트에서 고정이므로
  캐시 hit rate 가 높아 입력 비용 최대 ~90% 절감 + latency 감소.

입력 크기 4096+ tokens 일 때만 캐시 적용 권장 (Anthropic 안내). 본 엔진은 system 에
무조건 cache marker 붙이고, 실제 캐시 여부는 API 측에서 판단 (작으면 무시 — 안전).
"""
from __future__ import annotations

import os
from typing import Optional

from .base import LLMBackend, LLMResponse


_CLIENT = None


def _get_client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    try:
        import anthropic
    except ImportError:
        return None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    _CLIENT = anthropic.Anthropic(api_key=key)
    return _CLIENT


# Claude Code CLI 의 model alias → API 의 정식 model id 매핑.
# CLI 가 "claude-sonnet-4-6" 같은 짧은 이름 쓰는데 SDK 는 정식 snapshot id 선호.
# 실패 시 원본 그대로 넘김 (API 가 alias 지원하면 OK).
_MODEL_ALIAS = {
    "claude-sonnet-4-6": "claude-sonnet-4-5",  # alias 통용, API 가 latest 매핑
    "claude-opus-4-7": "claude-opus-4-5",
    "claude-haiku-4-5": "claude-haiku-4-5",
    # 이미 정식 id 인 경우 통과
}


def _resolve_model(model: str) -> str:
    return _MODEL_ALIAS.get(model, model)


class AnthropicSDKBackend(LLMBackend):
    name = "anthropic_sdk"

    def available(self) -> bool:
        return _get_client() is not None

    def generate(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2048,
        timeout: int = 60,
        cacheable_system: bool = False,
        **kwargs,
    ) -> LLMResponse:
        client = _get_client()
        if client is None:
            return LLMResponse(
                text="", model=model,
                error="anthropic_sdk: SDK unavailable or ANTHROPIC_API_KEY missing",
            )
        try:
            api_model = _resolve_model(model)
            # system 은 list[TextBlockParam] 형태로 보내야 cache_control 적용 가능
            if cacheable_system and system:
                system_param = [{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                system_param = system or ""

            msg = client.messages.create(
                model=api_model,
                max_tokens=max_tokens,
                system=system_param,
                messages=[{"role": "user", "content": user}],
                timeout=timeout,
            )
            text = "".join(
                b.text for b in getattr(msg, "content", [])
                if getattr(b, "type", "") == "text"
            ).strip()
            usage = getattr(msg, "usage", None)
            return LLMResponse(
                text=text,
                model=api_model,
                input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
                output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) if usage else 0,
            )
        except Exception as e:
            return LLMResponse(
                text="", model=model,
                error=f"anthropic_sdk: {type(e).__name__}: {str(e)[:200]}",
            )
