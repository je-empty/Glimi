# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""LLM 가격표 + 비용 추정 — kernel-side, platform-neutral.

비용은 **resolved API model id** (anthropic_sdk._MODEL_ALIAS 적용 후) 기준으로 매긴다.
LLMResponse.model 이 그 resolved id 를 담으므로 그대로 키로 쓰면 billed id 와 priced id 가
일치한다 (alias 불일치로 $0 으로 새는 버그 방지).

정직성 (HONEST — 절대 조작 금지):
  - SDK 경로는 실측 토큰 → 정확한 $.
  - CLI 경로 (--output-format text) 는 토큰 0 반환 → 호출자가 추정해서 estimated=1 로 기록.
  - ollama / echo 등 로컬 백엔드는 가격표에 없음 → $0 (무료). 알 수 없는 모델도 $0.

가격은 1,000,000 토큰당 USD. PRICING_AS_OF 가 대시보드에 노출되니 가격 수정 시 갱신.
"""
from __future__ import annotations

from typing import Optional

# 가격표 검증 시점 (claude-api skill, 2026-05-26 기준). 수정 시 반드시 갱신.
PRICING_AS_OF = "2026-05-26"

# $ per 1,000,000 tokens.
# cache_read ≈ 0.1× input rate, cache_write ≈ 1.25× input rate (5분 ephemeral TTL).
_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-4-8":   {"input": 5.0, "output": 25.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},  # sonnet-4-6 alias target
    "claude-haiku-4-5":  {"input": 1.0, "output": 5.0},
    # ollama:* / echo / 알 수 없는 모델 → 가격표 부재 → $0
}


def is_priced(model: Optional[str]) -> bool:
    """이 모델에 가격이 있는지 (= $ 표시가 의미 있는지). 로컬/미지 모델은 False."""
    return bool(model) and model in _PRICES


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """한 번의 LLM 호출 추정 비용 (USD). 가격표 없는 모델(로컬 등) → 0.0.

    cache 비용은 input rate 의 read 0.1× / write 1.25× 별도 요율 (flat 합산 아님).
    """
    p = _PRICES.get(model)
    if p is None:
        return 0.0  # local / unknown → free
    inr, outr = p["input"], p["output"]
    return (
        input_tokens * inr
        + output_tokens * outr
        + cache_read_tokens * inr * 0.1
        + cache_write_tokens * inr * 1.25
    ) / 1_000_000


def estimate_tokens_from_chars(text: Optional[str]) -> int:
    """API 키 없는 순수 CLI 구독 경로용 토큰 추정 — chars/4 휴리스틱.

    정확하지 않다 (영어 기준 대략치, 한국어/코드는 더 어긋남). 이 값으로 기록한 행은
    반드시 estimated=1 로 표시하고 대시보드에서 "est." 라벨. tiktoken 금지
    (OpenAI tokenizer — Claude 를 과소 계산).
    """
    if not text:
        return 0
    return max(0, len(text) // 4)
