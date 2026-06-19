# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Budget guard — monthly USD soft cap that degrades Claude routing to local.

Billing-critical: a runaway agent (background memory-extraction, judges, loops)
can silently burn Claude credits with no user present. This module reads a
monthly cap from ``GLIMI_MONTHLY_CAP_USD`` and, once month-to-date spend crosses
it, tells the two LLM choke-points to stop routing to Claude (degrade to local
Ollama, or a graceful placeholder when no local backend exists).

Design rules:
  - **Kernel-pure**: stdlib + ``glimi.store`` aggregation only. Never imports
    ``src.*`` or any platform/Discord type — the guard must ride along with the
    standalone kernel.
  - **Degrade open**: if we can't measure (no store, query error, cap unset),
    ``allow_claude`` returns True. We never block a legitimate call just because
    accounting is unavailable — a budget guard that fails closed would take the
    whole product down on a transient DB hiccup.
  - **Hot-path cheap**: month-to-date spend is cached ~15s per community so the
    per-turn guard check doesn't hammer SQLite. The cache is invalidated after
    each ``record_usage`` so a freshly-recorded (esp. blocked) row is reflected.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

# ~15s freshness window for the per-community spend cache. Short enough that a
# cap crossing is noticed within a few turns; long enough that a busy channel
# doesn't re-aggregate usage_records every single turn.
_CACHE_TTL_SEC = 15.0

# community-id (None for the unscoped/default community) → (cached_spend, expiry_monotonic)
_spend_cache: dict[Optional[str], tuple[float, float]] = {}
_cache_lock = threading.Lock()


def _cap_usd() -> float:
    """Configured monthly cap in USD. <=0 / unset / unparsable → 0.0 (no cap)."""
    raw = os.environ.get("GLIMI_MONTHLY_CAP_USD", "").strip()
    if not raw:
        return 0.0
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 0 else 0.0


def _month_start_iso() -> str:
    """First instant of the current UTC month, as UTC-aware ISO (matches the
    ts format usage_records is written with)."""
    now = datetime.now(timezone.utc)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first.isoformat()


def _store():
    """The same KernelStore the rest of the kernel uses (or None). Imported
    lazily to avoid an import cycle (runtime imports budget at guard points)."""
    try:
        from . import runtime as _rt
        return _rt.get_store()
    except Exception:
        return None


def _month_spend(community: Optional[str]) -> Optional[float]:
    """Month-to-date total_cost for ``community`` (cached ~15s). Returns None if
    spend can't be measured (no store / query error) so the caller degrades open."""
    now = time.monotonic()
    with _cache_lock:
        hit = _spend_cache.get(community)
        if hit is not None and hit[1] > now:
            return hit[0]

    store = _store()
    if store is None:
        return None
    try:
        agg = store.usage_spend(since=_month_start_iso(), community=community)
        spend = float((agg or {}).get("total_cost", 0.0) or 0.0)
    except Exception:
        return None

    with _cache_lock:
        _spend_cache[community] = (spend, time.monotonic() + _CACHE_TTL_SEC)
    return spend


def invalidate(community: Optional[str] = None) -> None:
    """Clear the spend cache. ``community=None`` clears every entry (called after
    each record_usage so the next guard check re-aggregates)."""
    with _cache_lock:
        if community is None:
            _spend_cache.clear()
        else:
            _spend_cache.pop(community, None)


def allow_claude(community: Optional[str]) -> bool:
    """True if routing this call to Claude is within budget.

    No cap configured → always True. If spend can't be measured → True (degrade
    open). Otherwise True only while month-to-date spend is strictly below cap."""
    cap = _cap_usd()
    if cap <= 0:
        return True
    spend = _month_spend(community)
    if spend is None:
        return True  # can't measure → never block
    return spend < cap
