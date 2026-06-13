"""Glimi Core — domain-neutral multi-agent kernel.

This package holds the reusable kernel that any application (Glimi Hangout, and
future apps) builds on. It must stay platform/domain-neutral: no Discord, no
hangout-specific content, no hardcoded community data.

Extraction is staged (see ``analysis/kernel_extraction_plan.md``):
- Phase 1 (done): ``llm`` (LLM backends) and ``tools`` (``<tools>`` protocol:
  registry, parser, dispatcher, validator, reference, result) moved here as-is.
- Phase 2 (planned): ``runtime`` / ``memory`` / ``conversation`` with a
  ``KernelStore`` ABC + ``AgentProfile`` protocol so the kernel stops importing
  the app's ``src.db`` / profile layer directly.

Import submodules explicitly, e.g. ``from src.glimi.llm import generate`` or
``from src.glimi.tools import run_tools``. Symbols are not eagerly re-exported
here to keep ``import src.glimi`` side-effect free.
"""

__all__ = ["llm", "tools"]
