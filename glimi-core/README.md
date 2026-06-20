# Glimi Core

The kernel behind [Glimi](../README.md) — a domain-neutral, platform-neutral multi-agent runtime, published to PyPI as **`glimi`**.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # offline: no API key, no network, no extra packages
chat.add_agent("nova", persona="a curious, upbeat friend")
print(chat.reply("nova", "hi!"))      # real models: backend="claude_cli" or "ollama"
```

## What's in here

- **`glimi/`** — the package: the agent runtime (per-agent model swap), a 5-layer persistent memory with time-based fact supersession, hardware-aware context budgeting (*Elastic Memory*), the `<tools><call/></tools>` protocol, the autonomous agent-to-agent conversation loop, a `KernelStore` ABC for dependency injection, and a store-driven observability dashboard (`glimi[dashboard]`: graph · memory · tool-call log · usage).
- **`examples/`** — minimal library starters (`research_buddies`, `dev_pair`, `dashboard_demo`).
- **`eval/`** — the evaluation harness (golden set + LLM-as-judge + regression gate).

State lives in storage (SQLite by default), not the prompt — so a character keeps its relationships, facts, and pinned memories across a restart and even a model swap. The kernel runs on the standard library alone (Claude via the CLI, Ollama via `urllib`); the dashboard extra adds FastAPI/Jinja.

## Install

```bash
pip install -e ".[dashboard]"      # from this folder (editable, dev)
# pip install "glimi[dashboard]"   # from PyPI, after 0.1.0 ships
```

## Apps built on it

- [**`glimi-community/`**](../glimi-community) — a cast of AI friends (the app Core was extracted *from*).
- [**`glimi-workspace/`**](../glimi-workspace) — a role-based work team (built on the kernel *alone*, zero Community imports).

---
AGPL-3.0-or-later · © 2026 Jaebin Sim
