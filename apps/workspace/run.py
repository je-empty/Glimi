#!/usr/bin/env python3
"""Glimi Workspace — a specialist team that genuinely INTERACTS, on Glimi Core.

A second app on the kernel, alongside the Discord "Community" social-sim — the
proof that **Glimi Core is a genuinely reusable core**. A manager agent
(**Coordinator**) plus three role specialists (**Researcher**, **Builder**,
**Critic**) take a work *goal* and produce a deliverable — not in one round-robin
room, but across several channels with distinct interaction shapes, exactly like
a real team:

1. **Owner ↔ Coordinator** (a DM): the owner gives the goal; the Coordinator
   plans and, at the end, delivers the synthesis.
2. **Coordinator ↔ each specialist** (per-specialist DMs): the Coordinator
   delegates a clear angle to the Researcher, the Builder, and the Critic.
3. **Specialist ↔ specialist** (internal A2A channels): pairs who should
   collaborate actually talk to each other — Researcher ↔ Critic debate the
   findings, Builder ↔ Researcher ground the plan — via the kernel's
   agent-to-agent engine (``runtime.generate_agent_to_agent``).
4. **Group** (a team channel): the whole team converges for one shared round.
5. The Coordinator delivers the final synthesis back in the owner DM.

As it runs, the app records the working **relationships** these interactions form
(``store.set_relationship``) — owner↔Coordinator (lead), Coordinator↔specialist
(manages), specialist↔specialist (collaborator, intimacy ∝ how much they talked).
Those relationships are exactly the edges the Core dashboard's connection graph
draws, so the **same** dashboard that serves Community now renders YOUR team as a
real interaction web. (A real backend ALSO grows these organically via the
kernel's memory extraction; here we also set them structurally so the graph is
populated on any backend, including the offline ``echo``.)

Built entirely on the ``glimi`` package: no Discord, no Community (``src``) code.

First run asks your **name** and **goal** (flags / env / interactive prompt).

Run it (offline echo by default — zero deps, no API key)::

    PYTHONPATH=. python apps/workspace/run.py --name Owner --goal "Plan our launch"

A real model (genuine collaboration + memory + organic relationship growth)::

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
    from team import (
        COLLAB_PAIRS, COLLAB_TURNS, COORDINATOR_DM, DEFAULT_GOAL,
        DELEGATION_CHANNELS, GROUP_CHANNEL, LABELS, SPECIALISTS, TEAM,
        resolve_setup,
    )
except ImportError:  # imported as apps.workspace.run
    from .team import (
        COLLAB_PAIRS, COLLAB_TURNS, COORDINATOR_DM, DEFAULT_GOAL,
        DELEGATION_CHANNELS, GROUP_CHANNEL, LABELS, SPECIALISTS, TEAM,
        resolve_setup,
    )

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8800

# Relationship intimacy (0–100) for the structural edges we record. The dashboard
# graph weights edges by intimacy, so a real team's hub (Coordinator) and its
# closest pairings stand out.
INTIMACY_LEAD = 80      # owner ↔ Coordinator
INTIMACY_MANAGES = 60   # Coordinator ↔ each specialist


def banner(backend: str, owner_name: str, goal: str) -> None:
    print("=" * 64)
    print("  Glimi Workspace — a specialist team on Glimi Core")
    print("=" * 64)
    print(f"  owner   : {owner_name}")
    print(f"  goal    : {goal}")
    print(f"  backend : {backend}")
    print(f"  team    : " + ", ".join(name for _, name, _, _ in TEAM))
    print(
        "  shape   : owner↔Coordinator (DM), Coordinator↔each specialist (DMs),\n"
        "            specialist↔specialist (A2A), and a group round — a real web."
    )
    if backend == "echo":
        print(
            "\n  Note: 'echo' is the OFFLINE placeholder backend — replies are\n"
            "  stubbed, so the flow is illustrative. The interaction topology and\n"
            "  the relationship graph are REAL regardless. Run with\n"
            "  GLIMI_LLM_BACKEND=claude_cli (or --backend ollama) for real work."
        )
    print("=" * 64 + "\n")


def _label(g: Glimi, speaker_id: str) -> str:
    """Display name for a speaker id (agent label, or the owner's name)."""
    if speaker_id == g.owner.id():
        return g.owner.name()
    return LABELS.get(speaker_id, speaker_id)


def dm(g: Glimi, agent_id: str, prompt: str, channel: str) -> str:
    """The owner prompts an agent in a DM channel; the agent reads the channel out
    of injected memory and replies back into it. (``g.reply`` logs the owner's
    prompt + the agent's reply to ``channel``.)"""
    reply = g.reply(agent_id, prompt, channel=channel)
    print(f"{LABELS[agent_id]}:\n{reply}\n")
    return reply


def a2a_exchange(g: Glimi, a: str, b: str, channel: str, brief: str,
                 turns: int) -> int:
    """Run a genuine agent-to-agent exchange between ``a`` and ``b`` on ``channel``.

    Drives the kernel's ``runtime.generate_agent_to_agent`` directly, alternating
    speakers, so each agent reads the shared channel (via injected memory) and
    answers the other — a real back-and-forth, not the owner relaying messages.
    (We drive the per-turn engine rather than ``conversation.start_conversation``
    so the offline demo and the tests stay fast and deterministic: no 2–5s
    inter-turn sleeps and no language-specific closure heuristics. The turns it
    produces are identical — ``start_conversation`` calls the same function.)

    Returns the number of turns that actually produced output.
    """
    g.store.set_channel_participants(channel, [a, b])
    print(f"--- {LABELS[a]} ↔ {LABELS[b]}  ({channel}) ---\n")
    spoken = 0
    pair = (a, b)
    for i in range(turns):
        speaker = pair[i % 2]
        listener = pair[(i + 1) % 2]
        ctx = (
            f"You and {LABELS[listener]} are working the goal together — {brief}"
            if i == 0 else
            f"Continue with {LABELS[listener]}: build on what was just said, "
            f"push back where warranted, and move toward something usable."
        )
        lines = g.runtime.generate_agent_to_agent(speaker, listener, channel, context=ctx)
        if lines:
            spoken += 1
            print(f"{LABELS[speaker]}:\n" + "\n".join(lines) + "\n")
    return spoken


def form_relationships(g: Glimi, collab_turns: dict[tuple[str, str], int]) -> None:
    """Record the working relationships the run's interactions formed.

    These become the connection-graph edges in the Core dashboard:

    - owner ↔ Coordinator  → ``lead``        (the Coordinator leads for the owner)
    - Coordinator ↔ each specialist → ``manages``
    - specialist ↔ specialist → ``collaborator``, intimacy ∝ how much they talked

    A real backend also grows these organically through memory extraction over the
    same channels; setting them structurally guarantees the graph is populated on
    *any* backend — the structural truth of who worked with whom.
    """
    owner_id = g.owner.id()
    g.store.set_relationship("coordinator", owner_id, rel_type="lead",
                             intimacy=INTIMACY_LEAD,
                             dynamics="Runs the workspace for the owner; takes the "
                                      "goal and delivers the synthesis.")
    for sid in SPECIALISTS:
        g.store.set_relationship("coordinator", sid, rel_type="manages",
                                 intimacy=INTIMACY_MANAGES,
                                 dynamics=f"Delegates an angle to {LABELS[sid]} and "
                                          f"folds the result into the plan.")
    for (a, b), n in collab_turns.items():
        # intimacy grows with how much the pair actually talked (clamped 40–90).
        intimacy = max(40, min(90, 40 + n * 12))
        g.store.set_relationship(a, b, rel_type="collaborator", intimacy=intimacy,
                                 dynamics=f"{LABELS[a]} and {LABELS[b]} worked the "
                                          f"goal together over {n} exchange(s).")


def run_workspace(g: Glimi, owner_name: str, goal: str) -> str:
    """Drive the full interaction topology on one shared store; return the
    final deliverable. Records relationships as the interactions form them."""
    owner_id = g.owner.id()
    print("--- The workspace opens ---\n")

    # 1) Owner ↔ Coordinator (DM): the owner gives the goal; the Coordinator
    #    greets, restates it, and lays out who it will hand which angle to.
    dm(
        g, "coordinator",
        f"You are {owner_name}'s Coordinator. {owner_name} brings this goal: "
        f"\"{goal}\".\nGreet {owner_name} by name, restate the goal in one crisp "
        f"sentence, then lay out the plan: which angle you'll hand the Researcher, "
        f"the Builder, and the Critic. Keep it tight.",
        channel=COORDINATOR_DM,
    )

    # 2) Coordinator ↔ each specialist (per-specialist DMs): real delegation. The
    #    Coordinator speaks into each specialist's channel; the specialist replies.
    print("--- The Coordinator delegates ---\n")
    angles = {
        "researcher": "gather the facts, options, and trade-offs the decision needs",
        "builder": "turn the direction into concrete, ordered next steps",
        "critic": "stress-test the emerging plan and name the biggest risk",
    }
    for sid in SPECIALISTS:
        ch = DELEGATION_CHANNELS[sid]
        # The Coordinator's delegating message, logged to the specialist's channel.
        g.store.set_channel_participants(ch, [owner_id, "coordinator", sid])
        g.store.log_message(
            ch, "coordinator",
            f"{LABELS[sid]}, on \"{goal}\": your angle is to {angles[sid]}. "
            f"Take it and report back.",
        )
        print(f"Coordinator → {LABELS[sid]} ({ch}):\n"
              f"  your angle is to {angles[sid]}.\n")
        # The specialist reads the delegation from the channel and responds.
        reply = g.reply(
            sid,
            f"Your Coordinator just gave you an angle on the goal \"{goal}\". "
            f"Read the channel and respond with your first concrete take: "
            f"what you'll dig into and one substantive starting point.",
            channel=ch,
        )
        print(f"{LABELS[sid]}:\n{reply}\n")

    # 3) Specialist ↔ specialist (A2A): pairs who should collaborate actually do.
    print("--- The specialists collaborate (agent-to-agent) ---\n")
    collab_turns: dict[tuple[str, str], int] = {}
    for a, b, channel, brief in COLLAB_PAIRS:
        n = a2a_exchange(g, a, b, channel, brief, COLLAB_TURNS)
        collab_turns[(a, b)] = n

    # 4) Group round: the whole team converges on one channel.
    print(f"--- The team converges ({GROUP_CHANNEL}) ---\n")
    g.store.set_channel_participants(
        GROUP_CHANNEL, [owner_id, "coordinator", *SPECIALISTS])
    g.reply(
        "coordinator",
        f"Open the group room for the team on \"{goal}\". In one or two lines, "
        f"call the team together and ask each specialist to drop their single most "
        f"important point.",
        channel=GROUP_CHANNEL,
    )
    print(f"Coordinator ({GROUP_CHANNEL}):\n  (called the team together)\n")
    for sid in SPECIALISTS:
        reply = g.reply(
            sid,
            f"You're in the group room with the whole team on \"{goal}\". Read the "
            f"room and drop your single most important point for the group.",
            channel=GROUP_CHANNEL,
        )
        print(f"{LABELS[sid]}:\n{reply}\n")

    # 5) Coordinator delivers the final synthesis — back in the owner DM.
    print("--- The Coordinator delivers ---\n")
    final = dm(
        g, "coordinator",
        f"As {owner_name}'s Coordinator, you've heard from the whole team across "
        f"the workspace. Deliver the final result for {owner_name}: a clear, "
        f"organized synthesis toward the goal \"{goal}\" — the decision, the plan, "
        f"and the top risk to watch. This is the deliverable.",
        channel=COORDINATOR_DM,
    )

    # Record the relationships these interactions formed → dashboard graph edges.
    form_relationships(g, collab_turns)
    return final


def summary(g: Glimi, owner_name: str, goal: str, final: str) -> None:
    """A clean closing summary: the interaction web + the deliverable."""
    print("--- Summary ---")
    print(f"  goal         : {goal}")

    # Channels touched — the shape of the interaction web.
    chans = g.store.get_channel_overview()
    if chans:
        print("  channels     : the team worked across "
              f"{len(chans)} channels (a real interaction web):")
        for c in sorted(chans, key=lambda c: c["channel"]):
            print(f"                 - {c['channel']} "
                  f"({c.get('msg_count', 0)} msgs)")

    # Relationships formed — exactly the dashboard's connection-graph edges.
    rels = _relationship_lines(g)
    if rels:
        print("  relationships: the run formed these working ties "
              "(these are the graph edges):")
        for line in rels:
            print(f"                 - {line}")

    print(f"\n  Deliverable for {owner_name}:")
    print("  " + "-" * 60)
    for line in (final or "").splitlines() or ["(no output)"]:
        print(f"  {line}")
    print("  " + "-" * 60 + "\n")


def _relationship_lines(g: Glimi) -> list[str]:
    """Human-readable lines for every relationship edge in the store (the same
    edges the dashboard graph draws), via the store-driven DashboardReader."""
    try:
        from glimi.dashboard import DashboardReader
    except Exception:
        return []
    snap = DashboardReader(g.store).snapshot()
    lines = []
    for e in snap.get("relationships", []):
        s, t = _label(g, e["source"]), _label(g, e["target"])
        lines.append(f"{s} ↔ {t}  [{e.get('type') or '?'}, "
                     f"intimacy {e.get('intimacy', 0)}]")
    return lines


def serve_dashboard(g: Glimi) -> int:
    """Serve the finished workspace in the Core dashboard (blocking).

    This is the payoff: the *same* store-driven dashboard that serves Community
    now renders YOUR work team — the connection graph (owner + Coordinator hubs +
    specialists + collaboration edges) plus each member's 5-layer memory. Needs
    the optional web deps (``pip install glimi[dashboard]``).
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
        description="A specialist team that genuinely interacts, built on Glimi Core.",
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

    print("Done — Coordinator + three specialists, one shared store, a real "
          "interaction web, kernel-only.")
    return 0


if __name__ == "__main__":
    # Allow `python apps/workspace/run.py` to import the sibling `team` module
    # without packaging gymnastics: ensure this dir is on sys.path.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
