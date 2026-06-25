# Glimi Core

**A domain-neutral, platform-neutral multi-agent kernel.**

Glimi Core (`glimi`) is the reusable harness underneath
[Glimi](https://github.com/jaebinsim/Glimi) — a layered runtime for populations
of LLM agents that keep persistent memory, talk to each other autonomously, and
stay observable. It is the kernel any application builds on; the
[Glimi Community](https://github.com/jaebinsim/Glimi) social simulation is the
flagship app that proves it out.

> ⚠️ **Alpha (0.1.0).** The API is still moving. Pin a version if you depend on it.

## What it gives you

- **Agent runtime** — per-agent model selection, prompt assembly, tool dispatch,
  anti-echo and channel discipline, autonomous agent-to-agent conversation.
- **5-layer persistent memory** — raw log → episodic rollup → semantic facts
  (subject·predicate·object) → relationships → pinned, with fact supersession.
  Memory lives in storage, not the prompt, so it survives restarts and model swaps.
- **`<tools>` protocol** — a model-dialect-neutral tool call format with a
  registry, parser, dispatcher, validator, and result plumbing.
- **Elastic Memory** — a context-budgeting layer that scales memory injection to
  the model's context window and guarantees the assembled prompt never overflows.
- **Storage / platform neutral** — the kernel talks to a `KernelStore` ABC and
  `AgentProfile` / `OwnerContext` / `KernelObserver` protocols. Bring your own
  database, profile source, and observability sink. **Zero transport / DB / web
  dependency in the kernel itself.**
- **Model-vendor neutral** — Claude (via the Claude CLI, no SDK required) and
  Ollama (via stdlib `urllib`) work out of the box; vLLM / llama.cpp fit the
  same backend seam.

## Install

```bash
pip install glimi              # kernel only — zero runtime dependencies
pip install "glimi[sdk]"       # + Anthropic Python SDK (instead of the Claude CLI)
```

The kernel deliberately ships with **no required dependencies**: it shells out to
the Claude CLI and calls Ollama over stdlib HTTP. Install an extra only if you
want a specific backend or the full showcase app.

## Quick start

The kernel ships a dependency-free in-memory store and an offline `echo` backend,
so this runs with **zero dependencies and no API key** (the `echo` backend doesn't
reach a real model — it lets you see the harness wire up and persist a chat):

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # offline: no deps, no API key, no network
chat.add_agent("nova", persona="A curious, upbeat companion who loves questions.")

print(chat.reply("nova", "Hi! What's your name?"))
print(chat.reply("nova", "Nice — tell me something fun."))
```

Switch to a real model by changing the backend (the rest stays the same):

```python
chat = Glimi(backend="claude_cli")    # uses your Claude CLI subscription (no SDK)
chat = Glimi(backend="ollama")        # fully local via Ollama (set GLIMI_OLLAMA_MODEL)
```

`Glimi` wires an in-memory `KernelStore`, a simple `ProfileProvider`/`OwnerContext`,
a `NullObserver`, and the chosen backend. To plug in your own database, implement
`KernelStore` (exported from `glimi`, alongside `InMemoryKernelStore`,
`SimpleProfileProvider`, `EchoBackend`, `LLMBackend`, …) and inject it via
`glimi.runtime.set_store(...)`. A complete production wiring (SQLite + web transport)
lives in the repo at `src/adapters/` and the Glimi Community app built on top.

Full documentation, architecture diagrams, the live observability dashboard, and
a working end-to-end application live in the monorepo:

**→ https://github.com/jaebinsim/Glimi**

## License

[AGPL-3.0](https://github.com/jaebinsim/Glimi/blob/main/LICENSE)
