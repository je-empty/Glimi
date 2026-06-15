# dev_pair

A **planner** agent breaks a task into steps; an **executor** agent carries them
out. Both share one in-memory store, and the plan is handed off *through that
store*.

## What it shows

- The **convenience API** (`from glimi import Glimi`): two agents, a few lines.
- The **planner → executor handoff via a shared store**: the planner writes its
  plan to a shared channel; the executor reads the plan back from that same
  channel history (not a Python variable) and acts on it.
- A **shared in-memory store**: the final shared log shows the planner's plan and
  the executor's report living in one channel.

## Run

Offline, zero dependencies, no API key (default `echo` backend):

```bash
# from the repo root, before `pip install glimi` lands:
PYTHONPATH=. python examples/dev_pair/run.py
```

Once `pip install glimi` is available, from this folder:

```bash
python run.py
```

## Backends

`echo` is the **offline placeholder** backend (the default): it just echoes your
last line, so planning/execution is illustrative, not real. With the offline
backend the script seeds a fixed, fictional plan for the executor to act on; with
a real backend it derives the steps from the planner's actual reply (read back
from the shared channel). Swap in a real model:

```bash
GLIMI_LLM_BACKEND=claude_cli python run.py     # needs the Claude CLI
python run.py --backend ollama                 # needs a local Ollama
```

Set the backend via the `GLIMI_LLM_BACKEND` env var or the `--backend` flag.

## Note: keep demos short

The demo runs one planning turn + one execution turn (4 messages on the shared
channel) on purpose. The memory layer rolls up raw messages into L1 summaries
once a channel passes `L1_BATCH_SIZE` (5) messages (`glimi/memory.py`). On this
branch the rollup path has a known offset-naive/aware datetime bug in
`get_memory_context` (fixed separately in `fix/memory-tz`). Keeping the channel
under the threshold avoids it. The offline `echo` backend never populates
memories anyway, so it is always clean; the caveat matters mainly for real
backends.
