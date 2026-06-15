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

## Sample output (real backend: claude_cli)

Generated with the `claude_cli` backend (the local Claude CLI subprocess); the
`echo` backend is the offline default. The runtime startup banner is trimmed;
the agent turns are verbatim.

```text
=== dev_pair (backend: claude_cli) ===
Using a real backend — expect genuine planning and execution.

--- Lead asks the planner to break down the task ---
[Runtime] Planner (planner) 활성화
Planner: Here's a quick 2-step breakdown:
1. **Locate the service entry point** — Find the main server file and identify the routing framework (Express, FastAPI, etc.) to understand where and how to add the endpoint.
2. **Add the /health endpoint** — Implement the endpoint to return a 200 status with a simple response (e.g., `{"status": "ok"}`), then verify it responds when hit.
Ready to dive in? I can help explore the codebase or build it out once you point me to the project.

--- Executor carries out 2 step(s) from the shared plan ---
[Runtime] Executor (executor) 활성화
[Memory] L1 추출: planner ch=dev-pair imp=2 ents=0 facts=0 rels=0
Executor: I'm in the home directory. I need you to point me to the web service project. Is there a specific project directory I should look into, or should I check a git repo that's already open?

--- Shared dev log (one store: planner wrote, executor read) ---
  Lead: Break this task into 2 short steps: add a /health endpoint to a small web service.
  Planner: Here's a quick 2-step breakdown:
  Planner: 1. **Locate the service entry point** — Find the main server file and identify the routing framework (Express, FastAPI, etc.) to understand where and how to add the endpoint.
  Planner: 2. **Add the /health endpoint** — Implement the endpoint to return a 200 status with a simple response (e.g., `{"status": "ok"}`), then verify it responds when hit.
  Planner: Ready to dive in? I can help explore the codebase or build it out once you point me to the project.
  Lead: Carry out the plan and report what was done — (1) define the route and its handler; (2) return a 200 with a small JSON body.
  Executor: I'm in the home directory. I need you to point me to the web service project. Is there a specific project directory I should look into, or should I check a git repo that's already open?

Done. The planner's plan and the executor's work share one channel.
```

## Note: keep demos short

The demo runs one planning turn + one execution turn (4 messages on the shared
channel) on purpose. The memory layer rolls up raw messages into L1 summaries
once a channel passes `L1_BATCH_SIZE` (5) messages (`glimi/memory.py`). On this
branch the rollup path has a known offset-naive/aware datetime bug in
`get_memory_context` (fixed separately in `fix/memory-tz`). Keeping the channel
under the threshold avoids it. The offline `echo` backend never populates
memories anyway, so it is always clean; the caveat matters mainly for real
backends.
