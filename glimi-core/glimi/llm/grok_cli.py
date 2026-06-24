# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
Grok CLI 백엔드 — `grok -p` subprocess 호출 래퍼.

claude_cli.ClaudeCLIBackend 의 형제. xAI 의 `grok` agentic CLI 를 headless
single-turn 모드로 호출한다:

    grok -p "<prompt>" --output-format plain -m grok-composer-2.5-fast

특징:
  - grok.com 로그인(OAuth)을 재사용 — 별도 API key 입력 불필요. 단 사용량은
    grok 계정 풀에서 차감되며, headless `--output-format plain` 은 per-call
    토큰을 반환하지 않으므로 사용량은 추정(estimated)으로만 기록한다 (claude_cli 와 동일).
  - grok 은 자체 모델 라인업을 가진다 (`grok-build`, `grok-composer-2.5-fast`).
    들어오는 claude-style model id 는 무시하고 항상 grok 모델을 쓴다.
    모델 선택: env `GLIMI_GROK_MODEL` (기본 "grok-composer-2.5-fast").
  - grok 은 agentic CLI 라 cwd 의 프로젝트 컨텍스트(CLAUDE.md/git/파일)를 흡수한다.
    → claude_cli 와 동일하게 HOME 에서 실행해 repo 컨텍스트 오염을 막는다.
  - prompt caching 미지원.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

from .base import LLMBackend, LLMResponse


_GROK_BIN_CACHE: Optional[str] = None

# grok 기본 모델 (env 미설정 시). grok models → grok-build | grok-composer-2.5-fast.
DEFAULT_GROK_MODEL = "grok-composer-2.5-fast"

# 알려진 설치 위치 (PATH 탐색 실패 시 fallback).
_GROK_FALLBACK = os.path.expanduser("~/.grok/bin/grok")


def _find_grok() -> Optional[str]:
    """grok CLI 경로 탐색. PATH + 일반 설치 위치."""
    global _GROK_BIN_CACHE
    if _GROK_BIN_CACHE is not None:
        return _GROK_BIN_CACHE or None
    p = shutil.which("grok")
    if p:
        _GROK_BIN_CACHE = p
        return p
    for cand in (
        _GROK_FALLBACK,
        os.path.expanduser("~/.local/bin/grok"),
        "/opt/homebrew/bin/grok",
        "/usr/local/bin/grok",
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            _GROK_BIN_CACHE = cand
            return cand
    _GROK_BIN_CACHE = ""  # 탐색 실패 캐시
    return None


def find_grok() -> Optional[str]:
    """Locate the Grok CLI binary (PATH + common install dirs), or None."""
    return _find_grok()


def _grok_model() -> str:
    """env GLIMI_GROK_MODEL → grok 모델 id. 들어오는 claude model 은 무시."""
    return (os.environ.get("GLIMI_GROK_MODEL") or "").strip() or DEFAULT_GROK_MODEL


def _combine_prompt(system: str, user: str) -> str:
    """grok 은 별도 --system-prompt 플래그가 없으므로 system 을 user 앞에 prepend.
    (claude_cli 는 --system-prompt 를 쓰지만 grok headless 는 -p 단일 프롬프트.)"""
    system = (system or "").strip()
    user = (user or "").strip()
    if system:
        return f"{system}\n\n{user}" if user else system
    return user


class GrokCLIBackend(LLMBackend):
    name = "grok_cli"

    def available(self) -> bool:
        return _find_grok() is not None

    def _base_args(self, system: str, user: str) -> list[str]:
        bin_path = _find_grok() or "grok"
        prompt = _combine_prompt(system, user)
        # grok 자체 모델 강제 — 들어온 claude model id 는 사용하지 않는다.
        args = [
            bin_path,
            "-p", prompt,
            "--output-format", "plain",
            "-m", _grok_model(),
        ]
        # effort 레버 — 캐주얼 페르소나 대화는 깊은 추론 불필요. 낮추면 지연 + SuperGrok
        # quota 소모 ↓. env GLIMI_GROK_EFFORT (기본 'low'). 'default'/'none' 이면 미지정.
        # NOTE: grok-composer-2.5-fast does NOT support --effort (400: no reasoningEffort)
        # → default is to NOT pass it. Only set GLIMI_GROK_EFFORT for reasoning models
        # (e.g. grok-build). Empty/unset = omit the flag (composer works).
        effort = (os.environ.get("GLIMI_GROK_EFFORT") or "").strip().lower()
        if effort and effort not in ("default", "none"):
            args += ["--effort", effort]
        return args

    def generate(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2048,
        timeout: int = 180,
        cacheable_system: bool = False,  # CLI 는 무시
        cli_cwd: Optional[str] = None,    # 오버라이드 — 기본은 HOME (repo 컨텍스트 회피)
        **kwargs,
    ) -> LLMResponse:
        # grok 은 자체 모델만 쓴다 → 응답 model 라벨도 실제 grok 모델로 기록.
        used_model = _grok_model()
        # grok streaming is slow (often 2-4 min for a full reply); honor a longer,
        # env-tunable ceiling so real persona replies aren't cut off (default 420s).
        eff_timeout = max(timeout, int(os.environ.get("GLIMI_GROK_TIMEOUT", "420")))
        args = self._base_args(system, user)
        # HOME 에서 실행: grok 은 agentic CLI 라 repo 루트에서 돌면 CLAUDE.md/git/파일을
        # 컨텍스트로 흡수해 페르소나 응답이 오염된다. HOME 엔 프로젝트 메타 없으니 안전.
        effective_cwd = cli_cwd or os.path.expanduser("~")
        try:
            result = subprocess.run(
                args,
                capture_output=True, text=True, timeout=eff_timeout,
                env={**os.environ},
                cwd=effective_cwd,
                stdin=subprocess.DEVNULL,  # headless — TTY 대기 방지
            )
            if result.returncode == 0 and result.stdout.strip():
                # 토큰은 plain 출력에서 알 수 없음 → 0 (estimated). 비용은 facade 가
                # 가격표 부재로 $0 처리 (claude_cli 와 동일한 정직 회계).
                return LLMResponse(text=result.stdout.strip(), model=used_model)
            err = (result.stderr or "").strip()[:200] or f"exit={result.returncode}"
            # degrade gracefully — 절대 raise 하지 않음. 빈 text + error 로 호출자에 위임.
            return LLMResponse(text="", model=used_model, error=f"grok_cli: {err}")
        except subprocess.TimeoutExpired:
            return LLMResponse(text="", model=used_model, error="grok_cli: timeout")
        except FileNotFoundError:
            return LLMResponse(text="", model=used_model, error="grok_cli: binary not found")
        except Exception as e:
            return LLMResponse(text="", model=used_model, error=f"grok_cli: {type(e).__name__}: {e}")
