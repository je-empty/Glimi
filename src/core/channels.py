"""Canonical channel classifier — the single source of truth for what a
channel id *means* and whether a human user may post into it.

Channel ids in Glimi are plain strings whose prefix encodes their role. Today
the prefix logic is duplicated across ~8 ``channel.startswith(...)`` call-sites
(handlers, sync, dashboard). This module is the canonical helper those sites will
collapse onto (that refactor is Phase 5 — DO NOT rewrite the call-sites here, we
only add + test the helper for now).

Prefix taxonomy
---------------
- ``dm-*``              : a 1:1 conversation between the human owner and one
                         agent.                       → user-postable.
- ``group-*``          : a multi-agent group the human participates in.
                         → user-postable.
- ``mgr-*``            : manager/system channels (e.g. ``mgr-system-log``,
                         ``mgr-...``). Internal plumbing surfaced for operators.
                         → NOT user-postable.
- ``internal-dm-*``    : agent-to-agent 1:1 backchannel.   → NOT user-postable.
- ``internal-group-*`` : agent-to-agent group backchannel. → NOT user-postable.

Rule of thumb: ONLY ``dm-*`` and ``group-*`` accept human input. Everything else
is internal/system and a user message addressed to it must be rejected by the
transport layer.

Pure string logic — no I/O, no ``discord`` import, no app imports.
"""
from __future__ import annotations

from typing import Literal

ChannelKind = Literal["dm", "group", "internal-dm", "internal-group", "mgr"]


def channel_kind(channel_id: str) -> ChannelKind:
    """Classify a channel id by its prefix.

    Order matters: the ``internal-`` prefixes are checked BEFORE the bare
    ``dm-`` / ``group-`` prefixes so that ``internal-dm-...`` is never
    misclassified as a user-facing ``dm``.

    Unknown / unprefixed ids fall back to ``"group"`` — historically arbitrary
    conversation keys (e.g. ``webchat-<user>``) behave like a user-facing group
    channel, which is the safe permissive default for the chat surface. Callers
    that need stricter handling should match explicit prefixes themselves.
    """
    cid = channel_id or ""
    if cid.startswith("internal-dm-") or cid == "internal-dm":
        return "internal-dm"
    if cid.startswith("internal-group-") or cid == "internal-group":
        return "internal-group"
    if cid.startswith("mgr-") or cid == "mgr":
        return "mgr"
    if cid.startswith("dm-") or cid == "dm":
        return "dm"
    if cid.startswith("group-") or cid == "group":
        return "group"
    # Unknown prefix → treat as a user-facing group channel (permissive default
    # for the web-chat surface where channel keys are arbitrary, e.g.
    # ``webchat-<user>``).
    return "group"


def is_user_postable(channel_id: str) -> bool:
    """True iff a human user is allowed to post into this channel.

    Only ``dm-*`` and ``group-*`` (and arbitrary user channels that fall back to
    ``group``) are postable. ``mgr-*`` / ``internal-dm-*`` / ``internal-group-*``
    are internal plumbing and reject human input.
    """
    return channel_kind(channel_id) in ("dm", "group")
