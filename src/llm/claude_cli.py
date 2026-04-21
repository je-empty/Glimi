"""
Claude Code CLI 백엔드 — `claude -p` subprocess 호출 래퍼.

특징:
  - 기존 Claude Code 구독 OAuth 재사용 (별도 API key 불필요)
  - prompt caching 미지원 (SDK 전용)
  - keychain 언락 필수 (qa.sh / start_dashboard.sh 에서 선 처리)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Iterator, Optional

from .base import LLMBackend, LLMResponse


_CLAUDE_BIN_CACHE: Optional[str] = None


def _find_claude() -> Optional[str]:
    """claude CLI 경로 탐색. PATH + 일반 설치 위치."""
    global _CLAUDE_BIN_CACHE
    if _CLAUDE_BIN_CACHE is not None:
        return _CLAUDE_BIN_CACHE or None
    # PATH 먼저
    p = shutil.which("claude")
    if p:
        _CLAUDE_BIN_CACHE = p
        return p
    # 흔한 위치
    for cand in (
        os.path.expanduser("~/.local/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            _CLAUDE_BIN_CACHE = cand
            return cand
    _CLAUDE_BIN_CACHE = ""  # 탐색 실패 캐시
    return None


class ClaudeCLIBackend(LLMBackend):
    name = "claude_cli"

    def available(self) -> bool:
        return _find_claude() is not None

    def _base_args(self, user: str, system: str, model: str) -> list[str]:
        bin_path = _find_claude() or "claude"
        args = [
            bin_path,
            "-p", user,
            "--output-format", "text",
            "--model", model,
        ]
        if system:
            args.extend(["--system-prompt", system])
        return args

    def generate(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2048,
        timeout: int = 60,
        cacheable_system: bool = False,  # CLI 는 무시
        cli_cwd: Optional[str] = None,    # 오버라이드 — 기본은 HOME (CLAUDE.md 회피)
        **kwargs,
    ) -> LLMResponse:
        args = self._base_args(user, system, model)
        env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"}
        # 기본 cwd = HOME. Glimi 프로젝트 루트에서 돌면 CLAUDE.md 가 로드돼 Claude Code 가
        # '프로젝트 코딩 작업' 컨텍스트 상속하면서 에이전트/메모리 추출 결과 오염 (refusal /
        # meta-commentary 섞임). HOME 에선 프로젝트 CLAUDE.md 없으니 안전.
        effective_cwd = cli_cwd or os.path.expanduser("~")
        try:
            result = subprocess.run(
                args,
                capture_output=True, text=True, timeout=timeout,
                env=env,
                cwd=effective_cwd,
            )
            if result.returncode == 0 and result.stdout.strip():
                return LLMResponse(text=result.stdout.strip(), model=model)
            err = (result.stderr or "").strip()[:200] or f"exit={result.returncode}"
            return LLMResponse(text="", model=model, error=f"claude_cli: {err}")
        except subprocess.TimeoutExpired:
            return LLMResponse(text="", model=model, error="claude_cli: timeout")
        except FileNotFoundError:
            return LLMResponse(text="", model=model, error="claude_cli: binary not found")
        except Exception as e:
            return LLMResponse(text="", model=model, error=f"claude_cli: {type(e).__name__}: {e}")

    def stream_lines(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 2048,
        timeout: int = 120,
        cacheable_system: bool = False,
        cli_cwd: Optional[str] = None,
        **kwargs,
    ) -> Iterator[str]:
        """CLI 의 stdout 을 실시간 라인으로 읽어 yield.
        (기존 runtime.py 의 streaming pattern — 여기로 이전 가능)."""
        args = self._base_args(user, system, model)
        env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL": "1"}
        effective_cwd = cli_cwd or os.path.expanduser("~")
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env, cwd=effective_cwd,
        )
        try:
            for line in proc.stdout:
                yield line.rstrip("\n")
        finally:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
