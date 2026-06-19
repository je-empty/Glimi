# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Concrete :class:`~glimi.store.KernelStore` implementations.

The kernel ships :class:`~glimi.stores.memory.InMemoryKernelStore` — a
dependency-free, in-process store so the convenience API runs out of the box.
Apps with a real database supply their own (see ``src/adapters/`` for the
SQLite-backed one used by Glimi Community).
"""
from .memory import InMemoryKernelStore

__all__ = ["InMemoryKernelStore"]
