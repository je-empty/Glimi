#!/usr/bin/env python3
"""research_buddies — two agents collaborate on a research topic.

Two researchers, Nova and Atlas, take turns on ONE shared channel. Each builds on
what the other just said. Because both agents live in the same ``Glimi`` instance,
they share a single in-memory store — so everything Nova says is visible to Atlas
(and vice versa) through the shared conversation history.

Runs offline with zero dependencies and no API key via the ``echo`` backend (the
default). Swap in a real model to get real collaboration:

    GLIMI_LLM_BACKEND=claude_cli python run.py     # needs the Claude CLI
    python run.py --backend ollama                 # needs a local Ollama

Run (from the repo root, before ``pip install glimi`` lands)::

    PYTHONPATH=. python examples/research_buddies/run.py

Once ``pip install glimi`` is available, plain ``python run.py`` works.
"""
from __future__ import annotations

import argparse
import os
import sys

from glimi import Glimi

# Shared collaboration channel — both agents read/write the same thread, so the
# single in-memory store is the shared "whiteboard" they build on.
CHANNEL = "research-lab"

TOPIC = "how tides work"

# Two short rounds keeps this channel at 4 messages — under memory.py's
# L1_BATCH_SIZE (5), so no L1 rollup runs. That matters for real backends:
# the rollup path hits a known offset-naive/aware datetime bug in
# get_memory_context (fixed separately in fix/memory-tz). Short demos stay clean.
ROUNDS = 2


def banner(backend: str) -> None:
    print(f"=== research_buddies (backend: {backend}) ===")
    if backend == "echo":
        print("Note: 'echo' is the OFFLINE placeholder backend — it just echoes\n"
              "your last line, so the 'collaboration' is illustrative, not real.\n"
              "Run with --backend claude_cli or ollama for genuine reasoning.\n")
    else:
        print("Using a real backend — expect genuine, model-generated turns.\n")


def last_contribution(chat: Glimi, speaker: str) -> str:
    """Most recent message that ``speaker`` posted to the shared channel.

    We read it back out of the shared store (not a local variable) on purpose:
    the point of the demo is that the partner's words are retrievable from the
    one shared channel history. Trim to a short snippet so the offline echo
    backend's transcript stays readable.
    """
    for msg in reversed(chat.history("nova", channel=CHANNEL)):
        if msg["speaker"] == speaker:
            text = msg["message"]
            # The echo backend wraps replies as '... You said: "<x>". Swap ...';
            # keep only a short snippet so the handoff is visible, not nested.
            return (text[:80] + "…") if len(text) > 80 else text
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Two research agents collaborating.")
    parser.add_argument(
        "--backend",
        default=os.environ.get("GLIMI_LLM_BACKEND", "echo"),
        help="LLM backend: echo (offline default), claude_cli, ollama, ...",
    )
    args = parser.parse_args()
    backend = args.backend

    banner(backend)

    chat = Glimi(backend=backend, owner_name="Lead")
    chat.add_agent("nova", name="Nova",
                   persona="A curious researcher who asks sharp questions and "
                           "proposes hypotheses.")
    chat.add_agent("atlas", name="Atlas",
                   persona="A pragmatic researcher who tests claims and adds "
                           "concrete detail.")

    # Kick off: ask Nova to open the investigation on the shared channel.
    print("--- Lead opens the investigation ---")
    opening = chat.reply("nova", f"Let's investigate {TOPIC}. Open with one idea.",
                         channel=CHANNEL)
    print(f"Nova: {opening}\n")

    # Take turns. Each turn explicitly hands the OTHER agent the partner's last
    # line from the shared channel, then asks them to build on it — demonstrating
    # that one agent's output is available to the other via the shared store.
    speakers = ["atlas", "nova"]
    for r in range(ROUNDS - 1):  # round 0 was Nova's opening
        for spk in speakers:
            partner = "nova" if spk == "atlas" else "atlas"
            handed = last_contribution(chat, partner)
            display = "Atlas" if spk == "atlas" else "Nova"
            print(f"--- {display} builds on the partner's last point ---")
            reply = chat.reply(
                spk,
                f"Your partner just said: \"{handed}\" — build on it with one "
                f"new point about {TOPIC}.",
                channel=CHANNEL,
            )
            print(f"{display}: {reply}\n")

    # Prove the shared store: every contribution lives in ONE channel history,
    # readable by either agent.
    print("--- Shared research log (one store, both agents) ---")
    for msg in chat.history("atlas", channel=CHANNEL):
        who = {"owner": "Lead", "nova": "Nova", "atlas": "Atlas"}.get(
            msg["speaker"], msg["speaker"])
        print(f"  {who}: {msg['message']}")

    print("\nDone. Both agents read and wrote the same shared channel history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
