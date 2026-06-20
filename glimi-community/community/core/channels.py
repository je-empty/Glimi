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


# Genuine system/log ``mgr-*`` channels — NOT owner conversations. The runtime
# ``<tools>`` log lives here; the degenerate bare ``mgr`` key is treated the same.
# Everything else ``mgr-*`` (``mgr-dashboard``, ``mgr-creator``, …) is, in the
# web model, simply a DM with that manager.
SYSTEM_CHANNELS = frozenset({"mgr-system-log", "mgr"})


def is_system_channel(channel_id: str) -> bool:
    """True for non-conversation system/log channels (e.g. the runtime ``<tools>``
    log) that must stay hidden from the owner's chat surface."""
    cid = channel_id or ""
    return channel_kind(cid) == "mgr" and cid in SYSTEM_CHANNELS


def is_owner_dm(channel_id: str) -> bool:
    """An owner↔single-agent DM.

    Includes ``dm-*`` AND the manager channels (``mgr-dashboard``, ``mgr-creator``,
    …) which — in the web model — are simply DMs with those managers. The
    ``mgr-*`` split between *DM* and *system* was a Discord artifact; on the web a
    manager channel IS a 1:1 DM. Excludes the system log (``is_system_channel``)
    and agent-to-agent backchannels (``internal-*``).
    """
    cid = channel_id or ""
    k = channel_kind(cid)
    if k == "dm":
        return True
    if k == "mgr" and not is_system_channel(cid):
        return True
    return False


def is_user_postable(channel_id: str) -> bool:
    """True iff a human user is allowed to post into this channel.

    Owner DMs (``dm-*`` and the manager channels ``mgr-dashboard`` / ``mgr-creator``
    / other non-system ``mgr-*``) and ``group-*`` accept human input. The system
    log (``mgr-system-log``), bare ``mgr``, and ``internal-*`` backchannels reject
    it.
    """
    return is_owner_dm(channel_id) or channel_kind(channel_id) == "group"
