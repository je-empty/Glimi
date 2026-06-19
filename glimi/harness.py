# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""High-level convenience API — wire an agent and chat in a few lines.

This is the friendly front door to the kernel. It assembles the moving parts the
kernel needs (an :class:`~glimi.stores.memory.InMemoryKernelStore`, a
:class:`~glimi.profiles_simple.SimpleProfileProvider`, an owner identity, a
:class:`~glimi.observability.NullObserver`, and a chosen LLM backend) and injects
them into the kernel ``runtime`` singleton, so you only write::

    from glimi import Glimi

    chat = Glimi(backend="echo")          # offline, zero deps, no API key
    chat.add_agent("nova", persona="A curious, upbeat companion.")
    print(chat.send("nova", "Hi there!"))

Switch backends by constructing with ``backend="claude_cli"`` (needs the Claude
CLI) or ``backend="ollama"`` (needs a local Ollama). With ``backend=None`` the
kernel's normal selection applies (SDK → CLI).

Import is side-effect free: nothing is wired until you instantiate :class:`Glimi`.
Instantiating sets the kernel's module-level store/profile/owner/observer globals,
so use this in a standalone process (not inside the Community app, which wires its
own adapters).
"""
from __future__ import annotations

import os
from typing import Optional

from . import memory as _memory
from . import runtime as _runtime
from .observability import NullObserver
from .profiles_simple import SimpleOwnerContext, SimpleProfileProvider
from .stores.memory import InMemoryKernelStore


class Glimi:
    """A self-contained harness: in-memory store + simple profiles + a backend.

    Args:
        backend: LLM backend name. ``"echo"`` (default) is offline and needs no
            API key or packages. Use ``"claude_cli"`` / ``"anthropic_sdk"`` /
            ``"ollama"`` for real models, or ``None`` to let the kernel select.
        owner_name / owner_id: the human the agents talk to.
        observer: a :class:`~glimi.observability.KernelObserver`; defaults to the
            silent :class:`NullObserver`.
    """

    def __init__(self, *, backend: Optional[str] = "echo",
                 owner_name: str = "You", owner_id: str = "owner",
                 observer=None) -> None:
        self.store = InMemoryKernelStore()
        self.profiles = SimpleProfileProvider()
        self.owner = SimpleOwnerContext(name=owner_name, owner_id=owner_id)
        self.observer = observer or NullObserver()
        self.runtime = _runtime.runtime
        self._backend = backend
        self._prev_backend_env = os.environ.get("GLIMI_LLM_BACKEND")

        # Inject our wiring into the kernel singletons (only on instantiation).
        # Both runtime and memory hold their own DI globals; the app wires both
        # (src/core/runtime.py + src/core/memory.py), so we do too — otherwise the
        # memory layer (get_memory_context / extraction) has no store.
        for mod in (_runtime, _memory):
            mod.set_store(self.store)
            mod.set_profiles(self.profiles)
            mod.set_owner(self.owner)
            mod.set_observer(self.observer)
        # Owner messages also feed memory extraction (matches app behavior).
        try:
            _memory.install_owner_extraction_hook()
        except Exception:
            pass

        # Route LLM calls through the chosen backend. The kernel reads
        # GLIMI_LLM_BACKEND when no per-call backend is threaded; setting it here
        # makes generate_response use our backend. None = leave selection alone.
        if backend:
            os.environ["GLIMI_LLM_BACKEND"] = backend

        # Register the owner in the store so memory-extraction hooks resolve it.
        self.store.upsert_user(owner_id, name=owner_name)

    # ── building the agent population ─────────────────────────────────
    def add_agent(self, agent_id: str, *, name: Optional[str] = None,
                  persona: str = "", agent_type: str = "persona",
                  model: Optional[str] = None, backend: Optional[str] = None,
                  speech: Optional[dict] = None) -> str:
        """Register an agent (id + persona). Returns the agent id.

        ``model`` sets a per-agent model override; ``backend`` (rare) forces a
        per-agent backend via the ``ollama:``-style model marker is not used here —
        prefer the harness-wide ``backend`` unless you know you need a mix.
        """
        display = name or agent_id
        # Per-agent backend escape hatch: encode as model marker the runtime reads.
        model_override = model
        if backend == "ollama" and not (model_override or "").startswith("ollama:"):
            model_override = "ollama:local"
        self.profiles.add(agent_id, name=display, persona=persona,
                          agent_type=agent_type, speech=speech)
        self.store.upsert_agent(agent_id, name=display, agent_type=agent_type,
                                model_override=model_override)
        return agent_id

    # ── chatting ──────────────────────────────────────────────────────
    def send(self, agent_id: str, message: str, *,
             channel: Optional[str] = None) -> list[str]:
        """Send the owner's ``message`` to ``agent_id``; return the reply line(s).

        Uses a per-agent DM channel by default so each agent keeps its own thread.
        """
        ch = channel or f"dm-{agent_id}"
        # Make sure the channel records both participants (used by channel context).
        self.store.set_channel_participants(ch, [self.owner.id(), agent_id])
        return self.runtime.generate_response(agent_id, ch, message)

    def reply(self, agent_id: str, message: str, *, channel: Optional[str] = None) -> str:
        """Like :meth:`send` but join the reply lines into one string."""
        return "\n".join(self.send(agent_id, message, channel=channel))

    def history(self, agent_id: str, *, channel: Optional[str] = None,
                limit: int = 50) -> list[dict]:
        """Recent messages in the agent's channel (oldest → newest)."""
        ch = channel or f"dm-{agent_id}"
        return self.store.get_recent_messages(ch, limit=limit)


def quickstart(agent_id: str = "nova", *, persona: str = "",
               name: Optional[str] = None, backend: Optional[str] = "echo") -> Glimi:
    """One-call setup: build a :class:`Glimi` harness with a single agent ready.

    Example::

        from glimi import quickstart
        chat = quickstart("nova", persona="A curious, upbeat companion.")
        print(chat.reply("nova", "Hi!"))
    """
    g = Glimi(backend=backend)
    g.add_agent(agent_id, name=name, persona=persona)
    return g
