#!/usr/bin/env python3
"""research_desk — a small team of specialist agents that build shared memory.

A persistent "research desk": three specialists with distinct roles — an **Editor**
who frames and synthesizes, a **Researcher** who digs in, and a **Skeptic** who
pokes holes — work one question over several rounds on a single shared channel.

Because all three live in the same ``Glimi`` instance they share **one store**:
every turn is logged, and as the conversation grows the kernel rolls raw turns up
into layered long-term memory (L0 → L1) and injects it back into later turns.
Nobody is handed the transcript by hand — each agent reads the desk out of memory.

This is Glimi Core used as a plain **library**: no Discord, no Community code — the
same engine that powers Glimi Community, in ~100 lines.

Offline by default (the ``echo`` backend: zero deps, no API key — replies are
stubbed, so the reasoning is illustrative). Swap in a real model for genuine
collaboration and meaningful memory::

    GLIMI_LLM_BACKEND=claude_cli python run.py     # needs the Claude CLI
    python run.py --backend ollama                 # needs a local Ollama

Run from the repo root (until ``pip install glimi`` lands)::

    PYTHONPATH=. python examples/research_desk/run.py
"""
from __future__ import annotations

import argparse
import os
import sys

from glimi import Glimi

DESK = "research-desk"  # the one shared channel the whole team works on
QUESTION = "Should a small team self-host its LLMs, or use a hosted API?"
ROUNDS = 2

# (id, display name, persona). Each agent could run a *different* model — e.g.
# add_agent("editor", ..., model="claude-sonnet-4-6") — and still share the store.
TEAM = [
    ("editor", "Editor",
     "Frames the question, assigns angles, and synthesizes findings into a verdict."),
    ("researcher", "Researcher",
     "Digs into specifics and brings concrete facts, numbers, and trade-offs."),
    ("skeptic", "Skeptic",
     "Stress-tests every claim and surfaces risks the others missed."),
]
LABEL = {aid: name for aid, name, _ in TEAM}
LABEL["owner"] = "Desk"


def banner(backend: str) -> None:
    print(f"=== research_desk (backend: {backend}) ===")
    if backend == "echo":
        print("Note: 'echo' is the OFFLINE placeholder backend — replies are stubbed,\n"
              "so the reasoning is illustrative. Run with --backend claude_cli (or\n"
              "ollama) for genuine collaboration and meaningful memory.\n")
    else:
        print("Real backend — expect genuine, model-generated turns + memory.\n")


def say(desk: Glimi, agent_id: str, prompt: str) -> None:
    """One turn: the desk prompts an agent; the agent reads the shared desk (via
    injected memory) and posts back to the same channel."""
    reply = desk.reply(agent_id, prompt, channel=DESK)
    print(f"{LABEL[agent_id]}: {reply}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="A specialist agent team sharing memory.")
    ap.add_argument(
        "--backend",
        default=os.environ.get("GLIMI_LLM_BACKEND", "echo"),
        help="LLM backend: echo (offline default), claude_cli, ollama, ...",
    )
    args = ap.parse_args()
    backend = args.backend
    banner(backend)

    # One Glimi instance == one shared store. We keep all three on the harness
    # backend for a zero-config demo; per-agent models would still share this store.
    desk = Glimi(backend=backend, owner_name="Desk")
    for aid, name, persona in TEAM:
        desk.add_agent(aid, name=name, persona=persona)

    print(f"--- The desk opens: {QUESTION} ---")
    say(desk, "editor",
        f"Open the desk on this question and say what to investigate: {QUESTION}")

    for r in range(1, ROUNDS + 1):
        print(f"--- Round {r} ---")
        say(desk, "researcher",
            f"As the Researcher, read the desk and add concrete findings on: {QUESTION}")
        say(desk, "skeptic",
            "As the Skeptic, read the desk and challenge the weakest claim so far.")

    print("--- The Editor synthesizes the desk's verdict ---")
    say(desk, "editor",
        "As the Editor, read the whole desk and give the team's current verdict.")

    # Memory lives in storage, not the prompt — and it is SHARED. Every turn from
    # all three specialists sits in one channel, readable by any agent. As the desk
    # grows the kernel rolls raw turns up into layered long-term memory (L1) and
    # extracts facts; it injects that back into later turns so nobody re-reads the
    # whole thread.
    log = desk.history("editor", channel=DESK, limit=999)
    print("--- Memory snapshot (one shared store) ---")
    print(f"  the full discussion ({len(log)} messages) lives in ONE shared channel,")
    print("  readable by any agent.")
    rolled = []
    for aid, name, _ in TEAM:
        try:
            n = len(desk.store.get_memories(aid, DESK, 1, limit=99))
        except Exception:
            n = 0
        if n:
            rolled.append(f"{name}={n}")
    if rolled:
        print("  Rolled up into long-term memory (L1): " + ", ".join(rolled))
    else:
        print("  (Run with a real backend to watch raw turns roll up into L1 memory + facts.)")

    print("\nDone — three personas, one shared persistent store, no Discord in sight.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
