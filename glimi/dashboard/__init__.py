"""Glimi dashboard — store-driven, app-agnostic dashboard.

This package is the dashboard slice of Glimi Core. It renders *any* agent
population from a :class:`~glimi.store.KernelStore` alone — no Community, no
Discord, no server control, read-only.

Two layers, split so the kernel stays **zero-dependency**:

- **Data layer (zero-dep).** :class:`~glimi.dashboard.reader.DashboardReader` is
  pure stdlib + the kernel's own ``KernelStore``. ``import glimi.dashboard``
  pulls *only* this — no FastAPI / Jinja / uvicorn. So the reader is usable from
  the zero-dep kernel install.
- **Web layer (the ``glimi[dashboard]`` extra).** The FastAPI app lives in
  :mod:`glimi.dashboard.app`, which imports FastAPI at module top. To keep the
  base zero-dep, this ``__init__`` does **not** import ``app`` — :func:`serve`
  lazy-imports it *inside the function*, so it only requires the extra when you
  actually start the server.

Read the population (zero-dep)::

    from glimi import Glimi
    from glimi.dashboard import DashboardReader

    g = Glimi(backend="echo", owner_name="Owner")
    g.add_agent("nova", persona="A curious companion.")
    g.reply("nova", "hi")
    DashboardReader(g.store).agents()

Serve the web dashboard in-process (needs ``pip install glimi[dashboard]``)::

    import glimi.dashboard
    glimi.dashboard.serve(g.store)   # → http://127.0.0.1:8800
"""
from __future__ import annotations

from .reader import DashboardReader

__all__ = ["DashboardReader", "serve"]


def serve(store, host: str = "127.0.0.1", port: int = 8800, **uvicorn_kwargs):
    """Run the read-only web dashboard for ``store`` in-process (blocking).

    Builds ``create_app(DashboardReader(store))`` and serves it with uvicorn at
    ``http://{host}:{port}``. This is the primary entry point: point it at your
    own :class:`~glimi.store.KernelStore` to view that population's graph, agents,
    memory, facts, relationships and channels.

    The web dependencies (FastAPI / uvicorn) are imported lazily *here*, not at
    package import — so ``import glimi.dashboard`` (and ``DashboardReader``) stay
    zero-dep. Install them with ``pip install glimi[dashboard]``.

    Args:
        store: a :class:`~glimi.store.KernelStore` to read from.
        host: bind address. Defaults to loopback; pass ``"0.0.0.0"`` to expose.
        port: TCP port (default 8800).
        **uvicorn_kwargs: forwarded to ``uvicorn.run`` (e.g. ``log_level``).
    """
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - import-guard message
        raise ImportError(
            "The web dashboard needs the optional web dependencies. "
            "Install them with:  pip install glimi[dashboard]"
        ) from exc

    from .app import create_app

    app = create_app(DashboardReader(store))
    uvicorn.run(app, host=host, port=port, **uvicorn_kwargs)

