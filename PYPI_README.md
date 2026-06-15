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
  database, profile source, and observability sink. **Zero Discord / DB / web
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

A single-line convenience API is still being finalized. The kernel is real and
dependency-free — these imports work today:

```python
from glimi.runtime import runtime, AgentRuntime
from glimi.conversation import start_conversation
from glimi.store import KernelStore            # storage contract — implement for your DB
from glimi.profiles import ProfileProvider, OwnerContext
from glimi.observability import KernelObserver
```

To run agents you supply concrete `KernelStore` / `ProfileProvider` /
`KernelObserver` implementations, inject them into the kernel
(`runtime.set_store(...)`, …), then drive the conversation engine. A complete,
working wiring (SQLite + Discord) lives in the repo at `src/adapters/` and the
Glimi Community app built on top.

Full documentation, architecture diagrams, the live observability dashboard, and
a working end-to-end application live in the monorepo:

**→ https://github.com/jaebinsim/Glimi**

## License

[Apache-2.0](https://github.com/jaebinsim/Glimi/blob/main/LICENSE)
