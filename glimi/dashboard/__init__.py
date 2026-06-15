"""Glimi dashboard — store-driven, app-agnostic dashboard data layer.

This package is the data layer of the (future) ``glimi[dashboard]`` extra. It
reads an agent population from a :class:`~glimi.store.KernelStore` alone and
exposes it as plain dicts — no web server, no Community, no Discord.

P1.0 (this slice) is **read-only and zero-dep**: pure stdlib + the kernel's own
``KernelStore``. The web layer (FastAPI / Jinja / Cytoscape) and the
``glimi[dashboard]`` packaging extra land in a later slice and will live behind
that extra so the kernel stays zero-dependency.

Usage::

    from glimi import Glimi
    from glimi.dashboard import DashboardReader

    g = Glimi(backend="echo", owner_name="Owner")
    g.add_agent("nova", persona="A curious companion.")
    g.reply("nova", "hi")
    DashboardReader(g.store).agents()
"""
from __future__ import annotations

from .reader import DashboardReader

__all__ = ["DashboardReader"]
