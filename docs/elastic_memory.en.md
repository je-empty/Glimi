# Elastic Memory — memory that fits any context window

[← README](../README.md)

Local models have small windows (Ollama 4096). A full Glimi prompt — character system + L0–L5 memory + chat history — often exceeds that, truncating early tokens. `Elastic Memory` (`glimi/context_budget.py`) manages this:

- **Memory scales with window** — baseline `num_ctx` 8192; 4096 shrinks, 16384 doubles recall.
- **Best-effort fit** — trims oldest conversation first; logs warning if even system prompt overflows.
- **Backend-agnostic** — works with Claude or any; mainly for locals (cloud 200 k rarely needs it).
- **Per-community, hardware-aware** — `community/core/system_specs.py` reads RAM/VRAM, suggests Low 4096 / Mid 8192 / High 16384 tiers, writes config like a quality slider.

The same agent runs at 4096 or 16384 without personality loss. Glimi trims by token budget so prompts stay within the set window — others trim history (CrewAI, Letta, OpenAI Agents SDK, AutoGen, LangGraph) but not by target size. Ollama's request to auto-match VRAM is still open.
