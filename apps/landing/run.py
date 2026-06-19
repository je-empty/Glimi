#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""CLI entry for the Glimi landing portal.

    PYTHONPATH=. python -m apps.landing.run --host 127.0.0.1 --port 8200

Link targets come from env (GLIMI_COMMUNITY_URL / GLIMI_WORKSPACE_URL); see
``server.py``.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="glimi-landing",
        description="The standalone Glimi landing portal (entry hub).",
    )
    ap.add_argument("--host", default="127.0.0.1",
                    help="Bind host (default 127.0.0.1; use 0.0.0.0 to expose).")
    ap.add_argument("--port", type=int, default=8200, help="Bind port (default 8200).")
    args = ap.parse_args(argv)
    try:  # imported as a package module
        from apps.landing.server import serve
    except ImportError:  # script / flat-dir on sys.path
        from server import serve  # type: ignore
    return serve(host=args.host, port=args.port)


if __name__ == "__main__":
    # Allow `python apps/landing/run.py` (flat-dir) to find sibling server.py.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
