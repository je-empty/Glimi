#!/usr/bin/env python3
"""dev_pair — a planner agent hands work to an executor agent.

Two agents share ONE in-memory store via a single ``Glimi`` instance:

  * ``planner`` breaks a task into a short list of steps.
  * ``executor`` reads the plan back from the shared channel and carries out the
    steps one by one.

The planner→executor handoff goes *through the shared store*: the executor does
not get the plan as a Python variable, it reads it out of the same channel
history the planner wrote to. That's the point — the store is the hand-off bus.

Runs offline with zero dependencies and no API key via the ``echo`` backend (the
default). Swap in a real model for genuine planning/execution:

    GLIMI_LLM_BACKEND=claude_cli python run.py     # needs the Claude CLI
    python run.py --backend ollama                 # needs a local Ollama

Run (from the repo root, before ``pip install glimi`` lands)::

    PYTHONPATH=. python examples/dev_pair/run.py

Once ``pip install glimi`` is available, plain ``python run.py`` works.
"""
from __future__ import annotations

import argparse
import os
import sys

from glimi import Glimi

# One shared channel = the hand-off bus between planner and executor.
CHANNEL = "dev-pair"

TASK = "add a /health endpoint to a small web service"

# The fictional plan the executor will carry out. With the offline echo backend
# the planner can't really decompose a task, so we seed a fixed plan and let the
# executor act on each step. With a real backend, derive the steps from the
# planner's actual reply instead (see the README note).
FALLBACK_STEPS = [
    "define the route and its handler",
    "return a 200 with a small JSON body",
]

# Keep the shared channel under memory.py's L1_BATCH_SIZE (5) so no L1 rollup
# runs: the rollup path hits a known offset-naive/aware datetime bug in
# get_memory_context (fixed separately in fix/memory-tz). 1 planning turn + 1
# execution turn = 4 messages on the shared channel — under the threshold, so
# short demos stay clean on this stacked branch (matters for real backends,
# which actually populate memories; the offline echo backend never does).


def banner(backend: str) -> None:
    print(f"=== dev_pair (backend: {backend}) ===")
    if backend == "echo":
        print("Note: 'echo' is the OFFLINE placeholder backend — it just echoes\n"
              "your last line, so planning/execution is illustrative, not real.\n"
              "Run with --backend claude_cli or ollama for genuine reasoning.\n")
    else:
        print("Using a real backend — expect genuine planning and execution.\n")


def planned_steps(chat: Glimi, backend: str) -> list[str]:
    """Return the steps the executor should carry out.

    With a real backend we'd parse the planner's reply (read back from the shared
    channel) into steps. The offline echo backend can't produce a real plan, so
    fall back to a fixed, fictional step list.
    """
    if backend != "echo":
        # Real backend: take the planner's last line from the SHARED channel and
        # split it into steps. (Kept simple — adapt to your model's format.)
        for msg in reversed(chat.history("planner", channel=CHANNEL)):
            if msg["speaker"] == "planner":
                parts = [p.strip(" .-") for p in msg["message"].splitlines()
                         if p.strip(" .-")]
                if len(parts) >= 2:
                    return parts[:3]
    return FALLBACK_STEPS


def main() -> int:
    parser = argparse.ArgumentParser(description="A planner + executor agent pair.")
    parser.add_argument(
        "--backend",
        default=os.environ.get("GLIMI_LLM_BACKEND", "echo"),
        help="LLM backend: echo (offline default), claude_cli, ollama, ...",
    )
    args = parser.parse_args()
    backend = args.backend

    banner(backend)

    chat = Glimi(backend=backend, owner_name="Lead")
    chat.add_agent("planner", name="Planner",
                   persona="A planner who breaks a task into a short, numbered "
                           "list of concrete steps.")
    chat.add_agent("executor", name="Executor",
                   persona="An executor who carries out one step at a time and "
                           "reports what was done.")

    # 1) Planner decomposes the task, writing to the shared channel.
    print("--- Lead asks the planner to break down the task ---")
    plan_reply = chat.reply(
        "planner",
        f"Break this task into 2 short steps: {TASK}.",
        channel=CHANNEL,
    )
    print(f"Planner: {plan_reply}\n")

    # 2) Executor carries out the plan. It reads the plan back from the SHARED
    #    store, then acts. We hand the steps in explicitly so the echo transcript
    #    is legible, but the plan itself came from the shared channel history.
    #    One execution turn keeps the shared channel at 4 messages (< rollup).
    steps = planned_steps(chat, backend)
    print(f"--- Executor carries out {len(steps)} step(s) from the shared plan ---")
    plan_text = "; ".join(f"({i}) {s}" for i, s in enumerate(steps, 1))
    reply = chat.reply(
        "executor",
        f"Carry out the plan and report what was done — {plan_text}.",
        channel=CHANNEL,
    )
    print(f"Executor: {reply}\n")

    # 3) Prove the handoff went through one shared store.
    print("--- Shared dev log (one store: planner wrote, executor read) ---")
    for msg in chat.history("executor", channel=CHANNEL):
        who = {"owner": "Lead", "planner": "Planner",
               "executor": "Executor"}.get(msg["speaker"], msg["speaker"])
        print(f"  {who}: {msg['message']}")

    print("\nDone. The planner's plan and the executor's work share one channel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
