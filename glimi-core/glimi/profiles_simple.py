# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Minimal, domain-neutral profile / owner implementations.

These satisfy the kernel's :mod:`glimi.profiles` protocols
(:class:`ProfileProvider` / :class:`OwnerContext`) from plain persona strings —
no database, no prompt-builder framework. They exist so the convenience API can
wire an agent in a couple of lines.

Everything here is fictional and generic on purpose: the kernel must never carry
real-person / community-specific content (see CLAUDE.md). Apps that need a rich
prompt builder supply their own provider (see ``src/adapters/`` for Community's).
"""
from __future__ import annotations

from typing import Any, Optional


class SimpleOwnerContext:
    """A plain owner identity built from a name + id.

    Implements :class:`glimi.profiles.OwnerContext`.
    """

    def __init__(self, name: str = "You", owner_id: str = "owner",
                 display_name: Optional[str] = None, call_name: Optional[str] = None,
                 profile: Optional[dict] = None) -> None:
        self._name = name
        self._id = owner_id
        self._display = display_name or name
        self._call = call_name or name
        self._profile = profile or {}

    def name(self) -> str:
        return self._name

    def id(self) -> str:
        return self._id

    def display_name(self) -> str:
        return self._display

    def call_name(self) -> str:
        return self._call

    def profile(self) -> dict:
        return dict(self._profile)


class SimpleProfileProvider:
    """In-memory profile registry built from persona strings.

    Implements :class:`glimi.profiles.ProfileProvider`. Holds a dict per agent
    that the kernel reads (``id`` / ``name`` / ``type`` / ``speech`` /
    ``relationship_to_owner``) and assembles a tiny system prompt from the
    persona text. Register agents with :meth:`add`.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, dict] = {}

    def add(self, agent_id: str, *, name: str, persona: str = "",
            agent_type: str = "persona", relationship_to_owner: Optional[dict] = None,
            speech: Optional[dict] = None) -> dict:
        prof = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "display_name": name,
            "persona": persona or f"{name} is a friendly conversational character.",
            "relationship_to_owner": relationship_to_owner or {},
            "speech": speech or {},
        }
        self._profiles[agent_id] = prof
        return dict(prof)

    # ── ProfileProvider protocol ──────────────────────────────────────
    def get(self, agent_id: str) -> Optional[dict]:
        prof = self._profiles.get(agent_id)
        return dict(prof) if prof else None

    def system_prompt(self, agent_id: str, include_profile_image_template: bool = False,
                      model: Optional[str] = None) -> str:
        prof = self._profiles.get(agent_id)
        if not prof:
            return ""
        return self._build_prompt(prof)

    def display_name(self, agent_id: str) -> str:
        prof = self._profiles.get(agent_id)
        return prof["display_name"] if prof else agent_id

    # ── prompt assembly (app concern in the real adapter; tiny here) ──
    @staticmethod
    def _build_prompt(prof: dict) -> str:
        lines = [
            f"You are {prof['name']}.",
            prof["persona"].strip(),
        ]
        speech = prof.get("speech") or {}
        style = speech.get("style") or speech.get("style_description")
        if style:
            lines.append(f"Speech style: {style}")
        lines.append(
            "Stay in character. Reply naturally and briefly, as in a chat."
        )
        return "\n".join(l for l in lines if l)


class SimpleAgentProfile:
    """An object form of an agent persona satisfying :class:`glimi.profiles.AgentProfile`.

    Optional convenience for callers who prefer attribute access over the dict
    the provider stores. The kernel itself reads the dict from the provider; this
    is offered for completeness / typing.
    """

    def __init__(self, agent_id: str, name: str, *, persona: str = "",
                 agent_type: str = "persona", relationship_to_owner: Any = None,
                 speech: Any = None) -> None:
        self._id = agent_id
        self._name = name
        self._type = agent_type
        self._persona = persona or f"{name} is a friendly conversational character."
        self._relationship = relationship_to_owner or {}
        self._speech = speech or {}

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> str:
        return self._type

    @property
    def display_name(self) -> str:
        return self._name

    @property
    def relationship_to_owner(self) -> Any:
        return self._relationship

    @property
    def speech(self) -> Any:
        return self._speech

    def system_prompt(self, include_profile_image_template: bool = False) -> str:
        return SimpleProfileProvider._build_prompt({
            "name": self._name, "persona": self._persona, "speech": self._speech,
        })
