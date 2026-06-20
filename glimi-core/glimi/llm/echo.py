# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
Echo backend — an offline, zero-dependency LLM backend for the kernel.

Purpose: let the convenience API (and tests / examples) run end-to-end with **no
network, no API key, and no extra packages**. It never reaches a real model — it
synthesizes a short, deterministic reply from the prompt it is handed.

This is *not* a chat model. It exists so that ``runtime.generate_response`` has a
backend that always succeeds, so newcomers can see the harness wire up, persist
conversation, and trigger memory extraction before they plug in Claude or Ollama.

Selection: chosen when the caller passes ``backend="echo"`` or sets
``GLIMI_LLM_BACKEND=echo``. It is never selected automatically — the default
backend selection (SDK → CLI) is unchanged.
"""
from __future__ import annotations

import re
from typing import Iterator

from .base import LLMBackend, LLMResponse


def _last_user_line(user: str) -> str:
    """Pull the most recent speaker line out of the assembled prompt.

    The runtime builds a transcript like ``Name: message`` lines; the final line
    is the current turn's user message. Fall back to the whole text otherwise.
    """
    if not user:
        return ""
    lines = [ln.strip() for ln in user.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    last = lines[-1]
    # Strip a leading "Speaker: " prefix if present.
    m = re.match(r"^[^:\n]{1,40}:\s*(.+)$", last)
    return (m.group(1) if m else last).strip()


def _persona_name(system: str) -> str:
    """Best-effort persona name from the system prompt (purely cosmetic).

    Domain-neutral: if nothing obvious is found, no name is used.
    """
    if not system:
        return ""
    # Common patterns the kernel/app emit: "You are X" / "너는 X" / "이름: X".
    for pat in (
        r"[Yy]ou are\s+([A-Za-z][\w'\-]{0,30})",
        r"너는\s+([^\s,.!?]{1,20})",
        r"(?:이름|name)\s*[:：]\s*([^\s,.!?\n]{1,20})",
    ):
        m = re.search(pat, system)
        if m:
            return m.group(1).strip()
    return ""


class EchoBackend(LLMBackend):
    """Deterministic offline backend. Always available; never hits the network."""

    name = "echo"

    def available(self) -> bool:
        return True

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
        text = self._compose(system, user)
        return LLMResponse(text=text, model=model or "echo")

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
        for line in self._compose(system, user).split("\n"):
            yield line

    @staticmethod
    def _compose(system: str, user: str) -> str:
        """Build a short, deterministic, no-network reply.

        Echoes the user's last line back inside a friendly acknowledgement so the
        reply is obviously a placeholder while still exercising the full pipeline
        (logging, parsing, memory trigger). Same input → same output.
        """
        last = _last_user_line(user)
        name = _persona_name(system)
        opener = f"[{name}] " if name else ""
        if not last:
            return f"{opener}(echo) Hi! I'm running on the offline echo backend."
        return f'{opener}(echo) You said: "{last}". Swap in a real backend to chat for real.'
