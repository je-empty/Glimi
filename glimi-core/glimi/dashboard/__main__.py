# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""``python -m glimi.dashboard`` — serve a tiny demo population.

The primary entry point is in-process :func:`glimi.dashboard.serve(store)` against
*your* store. A store can't be "located" generically from the command line (it
lives in the host process), so this module-run builds a small offline ``echo``
population purely so the command does something useful out of the box — handy for
a quick look at the dashboard UI without writing a script.

    python -m glimi.dashboard                 # → http://127.0.0.1:8800
    python -m glimi.dashboard --host 0.0.0.0 --port 9000

Needs the web extra:  pip install glimi[dashboard]
"""
from __future__ import annotations

import argparse

from . import serve


def _demo_store():
    """A tiny, offline (``echo``) population so the demo run isn't empty."""
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner", owner_id="owner")
    g.add_agent("nova", name="Nova", persona="A curious, upbeat companion.")
    g.add_agent("sage", name="Sage", persona="A calm, thoughtful friend.")
    g.reply("nova", "hi there", channel="room")
    g.reply("sage", "good to meet you", channel="room")
    g.store.set_relationship("nova", "sage", rel_type="friend", intimacy=58,
                             dynamics="easy rapport")
    g.store.set_relationship("nova", "owner", rel_type="friend", intimacy=64)
    g.store.add_memory("nova", "room", level=1,
                       content="Owner greeted everyone in #room.", importance=6)
    g.store.add_memory("nova", "room", level=2,
                       content="Nova and Sage first met here.", importance=7,
                       is_pinned=True)
    g.store.add_fact("nova", subject="Owner", predicate="likes", object_value="coffee")
    return g.store


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m glimi.dashboard",
                                 description="Serve the Glimi Core dashboard for a demo population.")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8800, help="port (default: 8800)")
    args = ap.parse_args()

    store = _demo_store()
    print(f"Glimi Core dashboard (demo population) → http://{args.host}:{args.port}")
    serve(store, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
