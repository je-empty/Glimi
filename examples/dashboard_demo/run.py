#!/usr/bin/env python3
"""dashboard_demo — view a Glimi population in the Core web dashboard.

Builds a tiny offline (``echo``) population — a manager plus two personas, a few
turns, a couple of relationships and some seeded memory/facts — then serves the
**store-driven, read-only** Glimi Core dashboard against that population's store.

This is the ``glimi[dashboard]`` extra used the intended way: ``serve(store)``
runs the web UI in-process against the caller's own store. No Discord, no
Community, no server control — just the graph + agents + memory + channels.

Run from the repo root (needs the web extra)::

    pip install "glimi[dashboard]"        # or:  pip install -e ".[dashboard]"
    PYTHONPATH=. python examples/dashboard_demo/run.py
"""
from __future__ import annotations

import os
import sys

# Allow running directly (``python examples/dashboard_demo/run.py``) without
# setting PYTHONPATH: add the repo root (three levels up) to sys.path if ``glimi``
# isn't already importable (e.g. via ``pip install -e .``).
try:
    import glimi  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from glimi import Glimi
import glimi.dashboard

g = Glimi(backend="echo", owner_name="Owner", owner_id="owner")
g.add_agent("hana", name="Hana", persona="The team's warm coordinator.", agent_type="mgr")
g.add_agent("nova", name="Nova", persona="A curious, upbeat companion.")
g.add_agent("sage", name="Sage", persona="A calm, thoughtful friend.")

# A few turns so channels + memory have something to show.
for msg in ("hi everyone", "what are we working on today?"):
    g.reply("hana", msg, channel="lobby")
g.reply("nova", "excited to be here!", channel="lobby")
g.reply("sage", "let's get started", channel="lobby")

# Relationships (drive the connection graph) + a little memory/facts.
g.store.set_relationship("nova", "sage", rel_type="friend", intimacy=62, dynamics="easy rapport")
g.store.set_relationship("nova", "owner", rel_type="friend", intimacy=70)
g.store.set_agent_emotion("nova", "cheerful", 7)
g.store.add_memory("nova", "lobby", level=2, content="The team met for the first time.",
                   importance=7, is_pinned=True)
g.store.add_fact("nova", subject="Owner", predicate="likes", object_value="coffee")

print("Glimi Core dashboard → http://127.0.0.1:8800  (Ctrl-C to stop)")
glimi.dashboard.serve(g.store, host="127.0.0.1", port=8800)
