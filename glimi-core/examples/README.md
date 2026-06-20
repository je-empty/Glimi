# Glimi examples

Lightweight, runnable starters that use **Glimi Core** directly — no Community
social-sim scaffolding. Each one runs **offline, with zero dependencies and no
API key** via the `echo` backend, and swaps to a real model with one flag.

| Example | What it shows |
|---|---|
| [`research_buddies/`](research_buddies/) | Two agents collaborate on a research topic — they take turns, each building on the other's contribution, sharing one in-memory store. |
| [`dev_pair/`](dev_pair/) | A planner breaks a task into steps and an executor carries them out — the planner → executor handoff goes through one shared store. |

## Run any example

Offline by default (no API key, no extra packages):

```bash
# from the repo root, before `pip install glimi` lands:
PYTHONPATH=. python examples/research_buddies/run.py
PYTHONPATH=. python examples/dev_pair/run.py
```

Once `pip install glimi` is available, run a script directly from its folder:

```bash
python run.py
```

## Swap the backend

`echo` is the **offline placeholder** backend (the default) — it echoes your last
line so the pipeline runs without a model. For real output:

```bash
GLIMI_LLM_BACKEND=claude_cli python run.py     # needs the Claude CLI
python run.py --backend ollama                 # needs a local Ollama
```

Both the `GLIMI_LLM_BACKEND` env var and the `--backend` flag are honored.

## Why the demos are short

Each example runs only a handful of exchanges. The memory layer rolls raw
messages into L1 summaries once a channel passes `L1_BATCH_SIZE` (5) messages
(`glimi/memory.py`); on this branch that rollup path hits a known
offset-naive/aware datetime bug in `get_memory_context` (fixed separately in
`fix/memory-tz`). Keeping each channel under the threshold sidesteps it. The
offline `echo` backend never populates memories, so it's always clean — the
caveat matters mainly when you swap in a real backend.
