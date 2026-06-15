"""Observability sink the Glimi kernel writes to.

The kernel emits structured runtime signals (system notices, per-agent thinking
traces, chat lines, thinking start/stop markers) but must not depend on the
app's concrete logger / dashboard plumbing. It writes to this protocol; the app
wires it to its log writer + live dashboard. The default :class:`NullObserver`
makes the kernel usable standalone (e.g. in tests / examples) with no sink.

This is the seam that externalizes the ~80 ``log_writer.*`` call sites currently
inlined in the runtime (handled during the runtime migration).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class KernelObserver(Protocol):
    def system(self, message: str) -> None: ...
    def agent_thinking(self, agent_id: str, line: str) -> None: ...
    def chat(self, channel: str, speaker: str, message: str) -> None: ...
    def mark_thinking(self, agent_id: str, channel: str = "") -> None: ...
    def mark_done(self, agent_id: str) -> None: ...
    def is_thinking(self, agent_id: str) -> bool: ...


class NullObserver:
    """No-op observer — kernel runs silently when the app wires no sink."""

    def system(self, message: str) -> None:  # noqa: D401
        pass

    def agent_thinking(self, agent_id: str, line: str) -> None:
        pass

    def chat(self, channel: str, speaker: str, message: str) -> None:
        pass

    def mark_thinking(self, agent_id: str, channel: str = "") -> None:
        pass

    def mark_done(self, agent_id: str) -> None:
        pass

    def is_thinking(self, agent_id: str) -> bool:
        return False
