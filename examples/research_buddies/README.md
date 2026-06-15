# research_buddies

Two research agents — **Nova** and **Atlas** — collaborate on a topic by taking
turns on a single shared channel. Each turn builds on what the other just said.

## What it shows

- The **convenience API** (`from glimi import Glimi`): wire two agents in a few lines.
- A **shared in-memory store**: both agents live in one `Glimi` instance, so
  everything one writes is readable by the other. The script reads the partner's
  previous contribution back out of the shared channel history (not a Python
  variable) before each turn, and prints the full shared log at the end.
- The **planner/collaborator handoff via the store** — the store is the bus the
  agents talk through.

## Run

Offline, zero dependencies, no API key (default `echo` backend):

```bash
# from the repo root, before `pip install glimi` lands:
PYTHONPATH=. python examples/research_buddies/run.py
```

Once `pip install glimi` is available, from this folder:

```bash
python run.py
```

## Backends

`echo` is the **offline placeholder** backend (the default): it just echoes your
last line, so the collaboration is illustrative, not real. Swap in a real model
for genuine reasoning:

```bash
GLIMI_LLM_BACKEND=claude_cli python run.py     # needs the Claude CLI
python run.py --backend ollama                 # needs a local Ollama
```

Set the backend via the `GLIMI_LLM_BACKEND` env var or the `--backend` flag.

## Note: keep demos short

The demo runs only a couple of exchanges on purpose. The memory layer rolls up
raw messages into L1 summaries once a channel passes `L1_BATCH_SIZE` (5) messages
(`glimi/memory.py`). On this branch the rollup path has a known
offset-naive/aware datetime bug in `get_memory_context` (fixed separately in
`fix/memory-tz`). Keeping each channel under the threshold avoids it. The offline
`echo` backend never populates memories anyway, so it is always clean; the caveat
matters mainly for real backends.
