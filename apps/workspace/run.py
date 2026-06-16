#!/usr/bin/env python3
"""Glimi Workspace — a persistent specialist team for real work, on Glimi Core.

A second app on the kernel, alongside the Discord "Community" social-sim — the
proof that **Glimi Core is a genuinely reusable core**. A manager agent
(**Coordinator**) plus three role specialists (**Researcher**, **Builder**,
**Critic**) take a work *goal* and produce a deliverable, all on one shared
``Glimi`` store, then you can view the team in the very same Core dashboard that
serves Community.

Built entirely on the ``glimi`` package: no Discord, no Community (``src``) code.
The agents never get the transcript by hand — they read the shared workspace out
of the kernel's injected memory, exactly like a real team reading the room.

First run asks your **name** and **goal** (flags / env / interactive prompt), then:

1. The Coordinator greets you, restates the goal, and assigns the specialists.
2. Two rounds: Researcher → Builder → Critic each contribute, reading the shared
   workspace from memory.
3. The Coordinator synthesizes the final deliverable.

Run it (offline echo by default — zero deps, no API key)::

    PYTHONPATH=. python apps/workspace/run.py --name Owner --goal "Plan our launch"

A real model (genuine collaboration + memory)::

    GLIMI_LLM_BACKEND=claude_cli PYTHONPATH=. python apps/workspace/run.py
    PYTHONPATH=. python apps/workspace/run.py --backend ollama

View the finished team in the Core dashboard (needs ``pip install glimi[dashboard]``)::

    PYTHONPATH=. python apps/workspace/run.py --serve   # → http://127.0.0.1:8800
"""
from __future__ import annotations

import argparse
import os
import sys

from glimi import Glimi

# Import the sibling ``team`` module whether this file is run as a script
# (``python apps/workspace/run.py`` — its dir is on sys.path[0]) or imported as a
# package module (``apps.workspace.run`` — use a relative import). Either way the
# kernel boundary holds: ``team`` imports nothing from glimi/src/discord.
try:  # script / flat-dir on sys.path
    from team import DEFAULT_GOAL, LABELS, TEAM, resolve_setup
except ImportError:  # imported as apps.workspace.run
    from .team import DEFAULT_GOAL, LABELS, TEAM, resolve_setup

WORKSPACE = "workspace"  # the one shared channel the whole team works on
ROUNDS = 2
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8800


def banner(backend: str, owner_name: str, goal: str) -> None:
    print("=" * 64)
    print("  Glimi Workspace — a specialist team on Glimi Core")
    print("=" * 64)
    print(f"  owner   : {owner_name}")
    print(f"  goal    : {goal}")
    print(f"  backend : {backend}")
    print(f"  team    : " + ", ".join(name for _, name, _, _ in TEAM))
    if backend == "echo":
        print(
            "\n  Note: 'echo' is the OFFLINE placeholder backend — replies are\n"
            "  stubbed, so the flow is illustrative. Run with\n"
            "  GLIMI_LLM_BACKEND=claude_cli (or --backend ollama) for real work."
        )
    print("=" * 64 + "\n")


def turn(g: Glimi, agent_id: str, prompt: str) -> str:
    """One turn: prompt an agent on the shared workspace channel. The agent reads
    the workspace out of injected memory (we do NOT hand it the transcript) and
    posts its reply back to the same channel for the rest of the team to read."""
    reply = g.reply(agent_id, prompt, channel=WORKSPACE)
    print(f"{LABELS[agent_id]}:\n{reply}\n")
    return reply


def run_workspace(g: Glimi, owner_name: str, goal: str) -> str:
    """Drive the full flow on one shared store; return the final deliverable."""
    print(f"--- The workspace opens ---\n")

    # 1) Coordinator: greet, restate the goal, assign the specialists.
    turn(
        g, "coordinator",
        f"You are opening the workspace for {owner_name}. The goal is: \"{goal}\".\n"
        f"Greet {owner_name} by name, restate the goal in one crisp sentence, then "
        f"introduce the team — Researcher, Builder, Critic — and assign each a clear "
        f"angle for working this goal. Keep it tight.",
    )

    # 2) Two rounds of specialist contributions, each reading the shared workspace.
    for r in range(1, ROUNDS + 1):
        print(f"--- Round {r} ---\n")
        turn(
            g, "researcher",
            f"As the Researcher, read the workspace so far and add concrete facts, "
            f"options, and trade-offs that move the goal forward: \"{goal}\".",
        )
        turn(
            g, "builder",
            f"As the Builder, read the workspace and turn what's been said into "
            f"concrete next steps / a plan toward the goal: \"{goal}\".",
        )
        turn(
            g, "critic",
            "As the Critic, read the workspace and stress-test the plan so far: "
            "name the biggest risk or gap, and a mitigation for it.",
        )

    # 3) Coordinator synthesizes the final deliverable.
    print("--- The Coordinator delivers ---\n")
    final = turn(
        g, "coordinator",
        f"As the Coordinator, read the entire workspace and deliver the final result "
        f"for {owner_name}: a clear, organized synthesis toward the goal \"{goal}\" — "
        f"the decision, the plan, and the top risk to watch. This is the deliverable.",
    )
    return final


def summary(g: Glimi, owner_name: str, goal: str, final: str) -> None:
    """A clean closing summary: shared-store stats + the deliverable."""
    log = g.history("coordinator", channel=WORKSPACE, limit=999)
    print("--- Summary ---")
    print(f"  goal       : {goal}")
    print(f"  turns       : {len(log)} messages in ONE shared workspace channel,")
    print(f"                readable by every member.")

    # Show raw turns rolling up into long-term memory (visible with a real backend).
    rolled = []
    for aid, name, _, _ in TEAM:
        try:
            n = len(g.store.get_memories(aid, WORKSPACE, 1, limit=99))
        except Exception:
            n = 0
        if n:
            rolled.append(f"{name}={n}")
    if rolled:
        print("  long-term L1: " + ", ".join(rolled))
    else:
        print("  long-term L1: (run a real backend to watch turns roll up into memory)")

    print(f"\n  Deliverable for {owner_name}:")
    print("  " + "-" * 60)
    for line in (final or "").splitlines() or ["(no output)"]:
        print(f"  {line}")
    print("  " + "-" * 60 + "\n")


def serve_dashboard(g: Glimi) -> int:
    """Serve the finished workspace in the Core dashboard (blocking).

    This is the payoff: the *same* store-driven dashboard that serves Community
    now renders YOUR work team — the connection graph plus each member's 5-layer
    memory. Needs the optional web deps (``pip install glimi[dashboard]``).
    """
    import glimi.dashboard

    url = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
    print(f"--- Serving the workspace in the Core dashboard at {url} ---")
    print("    (the same dashboard that serves Community — Ctrl-C to stop)\n")
    try:
        glimi.dashboard.serve(g.store, host=DASHBOARD_HOST, port=DASHBOARD_PORT)
    except ImportError as exc:
        print(f"Dashboard deps not installed: {exc}", file=sys.stderr)
        print("Install with:  pip install glimi[dashboard]", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="glimi-workspace",
        description="A persistent specialist team for real work, built on Glimi Core.",
    )
    ap.add_argument("--name", help="Owner name (else env GLIMI_WORKSPACE_NAME / prompt / default).")
    ap.add_argument("--goal", help=f"Work goal (else env / prompt / default: {DEFAULT_GOAL!r}).")
    ap.add_argument(
        "--backend",
        default=os.environ.get("GLIMI_LLM_BACKEND", "echo"),
        help="LLM backend: echo (offline default), claude_cli, ollama, ...",
    )
    ap.add_argument(
        "--serve", action="store_true",
        help="After the work, serve the team in the Core dashboard (default OFF).",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backend = args.backend

    setup = resolve_setup(name_flag=args.name, goal_flag=args.goal)
    banner(backend, setup.owner_name, setup.goal)

    # One Glimi instance == one shared store for the whole team.
    g = Glimi(backend=backend, owner_name=setup.owner_name)
    for aid, name, agent_type, persona in TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)

    final = run_workspace(g, setup.owner_name, setup.goal)
    summary(g, setup.owner_name, setup.goal, final)

    if args.serve:
        return serve_dashboard(g)

    print("Done — Coordinator + three specialists, one shared store, kernel-only.")
    return 0


if __name__ == "__main__":
    # Allow `python apps/workspace/run.py` to import the sibling `team` module
    # without packaging gymnastics: ensure this dir is on sys.path.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
