"""Glimi Core — domain-neutral multi-agent kernel.

This package holds the reusable kernel that any application (Glimi Community,
future apps, or your own) builds on. It stays platform/domain-neutral: no
Discord, no app-specific content, no hardcoded community data.

What's here:
- ``llm`` — pluggable LLM backends (Claude CLI / Anthropic SDK / Ollama / the
  offline ``echo`` backend) behind a small ``LLMBackend`` ABC.
- ``tools`` — the ``<tools>`` protocol (registry, parser, dispatcher, validator).
- ``runtime`` / ``memory`` / ``conversation`` — the agent engine, talking to the
  data store and persona layer only through abstract seams:
  ``KernelStore`` (``store``), ``ProfileProvider`` / ``OwnerContext``
  (``profiles``), and ``KernelObserver`` (``observability``). The kernel imports
  with **zero** Discord/DB dependency and installs as a standalone wheel.
- ``stores`` — a concrete, dependency-free ``InMemoryKernelStore``.
- ``harness`` — a high-level ``Glimi`` facade that wires everything together.

Quick start (offline, no API key, no extra packages)::

    from glimi import Glimi
    chat = Glimi(backend="echo")
    chat.add_agent("nova", persona="A curious, upbeat companion.")
    print(chat.reply("nova", "Hi there!"))

Switch to a real model with ``Glimi(backend="claude_cli")`` (Claude CLI) or
``Glimi(backend="ollama")`` (local Ollama).

``import glimi`` is side-effect free — nothing is wired or run until you
instantiate :class:`~glimi.quickstart.Glimi` (the headline classes below are
re-exported lazily).
"""

__all__ = [
    # submodules
    "llm",
    "tools",
    # high-level facade
    "Glimi",
    "quickstart",
    # building blocks (re-exported for direct use)
    "InMemoryKernelStore",
    "EchoBackend",
    "SimpleProfileProvider",
    "SimpleOwnerContext",
    "SimpleAgentProfile",
    "NullObserver",
    # seams (ABCs / protocols)
    "KernelStore",
    "ProfileProvider",
    "OwnerContext",
    "AgentProfile",
    "KernelObserver",
    "LLMBackend",
    "LLMResponse",
]

# Map public name → (module, attribute). Resolved lazily so plain ``import glimi``
# stays side-effect free (no runtime singleton construction / no backend touch).
_LAZY = {
    "Glimi": ("glimi.harness", "Glimi"),
    "quickstart": ("glimi.harness", "quickstart"),
    "InMemoryKernelStore": ("glimi.stores.memory", "InMemoryKernelStore"),
    "EchoBackend": ("glimi.llm.echo", "EchoBackend"),
    "SimpleProfileProvider": ("glimi.profiles_simple", "SimpleProfileProvider"),
    "SimpleOwnerContext": ("glimi.profiles_simple", "SimpleOwnerContext"),
    "SimpleAgentProfile": ("glimi.profiles_simple", "SimpleAgentProfile"),
    "NullObserver": ("glimi.observability", "NullObserver"),
    "KernelStore": ("glimi.store", "KernelStore"),
    "ProfileProvider": ("glimi.profiles", "ProfileProvider"),
    "OwnerContext": ("glimi.profiles", "OwnerContext"),
    "AgentProfile": ("glimi.profiles", "AgentProfile"),
    "KernelObserver": ("glimi.observability", "KernelObserver"),
    "LLMBackend": ("glimi.llm.base", "LLMBackend"),
    "LLMResponse": ("glimi.llm.base", "LLMResponse"),
}


def __getattr__(name: str):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'glimi' has no attribute {name!r}")
    import importlib
    mod = importlib.import_module(target[0])
    return getattr(mod, target[1])


def __dir__():
    return sorted(list(globals().keys()) + __all__)
