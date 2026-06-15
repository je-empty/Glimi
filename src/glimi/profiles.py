"""Profile / identity protocols the Glimi kernel depends on.

The kernel reasons about *agents* and the *owner* without knowing how the app
stores or builds them. The app supplies objects that structurally satisfy these
protocols (``typing.Protocol`` — no inheritance required).
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OwnerContext(Protocol):
    """The community owner's identity, from the kernel's point of view.

    Adapts the app's ``get_user_name`` / ``get_user_id`` / ... family.
    """

    def name(self) -> str: ...
    def id(self) -> str: ...
    def display_name(self) -> str: ...
    def call_name(self) -> str: ...
    def profile(self) -> dict: ...


@runtime_checkable
class AgentProfile(Protocol):
    """A single agent's persona surface the kernel reads.

    Mirrors the keys the runtime/memory currently read off the app's profile
    dict (``type``, ``name``, ``relationship_to_owner``, ``speech``) plus the
    derived display name and the assembled system prompt. The prompt-assembly
    itself stays an app concern; the kernel only consumes the result.
    """

    @property
    def id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def display_name(self) -> str: ...
    @property
    def relationship_to_owner(self) -> Any: ...
    @property
    def speech(self) -> Any: ...

    def system_prompt(self, include_profile_image_template: bool = False) -> str: ...


@runtime_checkable
class ProfileProvider(Protocol):
    """Resolves agent persona data by id (the app's profile cache + prompt builder).

    Lets the runtime keep its dynamic ``load_profile(agent_id)`` pattern without
    importing the app's profile/prompt modules. ``get`` returns the persona
    mapping the kernel reads (``type`` / ``name`` / ``relationship_to_owner`` /
    ``speech`` …); ``system_prompt`` builds the assembled prompt.
    """

    def get(self, agent_id: str) -> dict | None: ...
    def system_prompt(self, agent_id: str, include_profile_image_template: bool = False,
                      model: str | None = None) -> str: ...
    def display_name(self, agent_id: str) -> str: ...
