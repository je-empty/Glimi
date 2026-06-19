# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
LLM 백엔드 추상화 — Glimi 가 어떤 추론 엔진을 쓰는지 결정하는 레이어.

현재 지원:
  - `claude_cli` (기본): `claude -p` subprocess 호출 — Claude Code 구독 OAuth 사용
  - `anthropic_sdk`: Anthropic API (ANTHROPIC_API_KEY) + prompt caching
  - `local` (예정, stub): ollama/vllm/llama.cpp 로컬 엔진

선택 규칙:
  1) 환경변수 `GLIMI_LLM_BACKEND` 가 있으면 그 백엔드 우선
  2) `GLIMI_LLM_AGENT_MAP` (JSON) 로 agent_type 별 오버라이드 가능
     예: {"mgr": "anthropic_sdk", "creator": "anthropic_sdk", "persona": "claude_cli"}
  3) 기본: claude_cli
  4) SDK 선택됐는데 API key 없으면 CLI 로 자동 fallback + 경고 로그

공개 API:
  generate(system, user, *, model, agent_type="", timeout=60, ...) -> str
  stream_lines(system, user, *, model, ...) -> Iterator[str]    # 라인 단위 스트림

cache_control 지원:
  `cacheable_system=True` 로 넘기면 SDK 백엔드에서 system 을 5분 ephemeral cache 로 마킹.
  CLI 백엔드는 무시 (SDK 전용 기능).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass
class LLMResponse:
    """통일된 응답 객체 — 백엔드 구현과 무관."""
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return bool(self.text) and self.error is None


class LLMBackend(abc.ABC):
    """백엔드 구현체의 공통 인터페이스."""

    name: str = "base"

    @abc.abstractmethod
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
        """단일 완성 생성. 완료된 전체 텍스트 반환."""

    def stream_lines(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2048,
        timeout: int = 120,
        cacheable_system: bool = False,
        **kwargs,
    ) -> Iterator[str]:
        """라인 단위 스트림. 기본 구현은 generate() 의 출력을 라인으로 쪼개서 yield.
        진짜 실시간 스트림이 필요한 백엔드는 override."""
        resp = self.generate(
            system=system, user=user, model=model,
            max_tokens=max_tokens, timeout=timeout,
            cacheable_system=cacheable_system, **kwargs,
        )
        if resp.text:
            for line in resp.text.split("\n"):
                yield line

    @abc.abstractmethod
    def available(self) -> bool:
        """백엔드 사용 가능 여부 (바이너리 있음 / API key 있음 등)."""
