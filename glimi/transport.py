"""Platform-neutral chat transport seam.

These are the types that decouple the kernel chat brain from any concrete
delivery channel (Discord webhook, web WebSocket, Telegram API, ...). The kernel
emits *outbound* turns through an :class:`Outbox` and receives *inbound* turns as
:class:`InboundMessage` handed to an :class:`Inbox`. Concrete adapters
(``src/bot`` for Discord, ``src/platform`` for web chat) implement these
Protocols; the kernel only ever sees the abstract shapes.

Hard rule: this module is stdlib + ``typing`` ONLY. No app imports, no
``discord`` import, no FastAPI/Starlette. It must stay importable standalone so
the kernel never grows a platform dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class Speaker:
    """Who is producing an outbound turn (an agent persona / mgr / creator).

    ``avatar_url`` is optional metadata an adapter may use to render the turn
    (e.g. a Discord webhook avatar or a web bubble avatar).
    """

    agent_id: str
    display_name: str
    avatar_url: Optional[str] = None


@dataclass(frozen=True)
class ImagePart:
    """An image attached to a turn — either inline bytes or a URL reference.

    Exactly one of ``data`` / ``url`` is expected to be set in practice, but the
    type does not enforce it (adapters decide how to serialize). ``caption`` is
    optional human-readable text shown alongside the image.
    """

    data: Optional[bytes] = None
    url: Optional[str] = None
    filename: str = "image.png"
    caption: str = ""


@runtime_checkable
class Outbox(Protocol):
    """Sink the kernel writes outbound turns to.

    Every method is awaitable so adapters can do network I/O. Each returns an
    opaque message id string (adapter-defined; may be empty if the transport has
    no addressable message handle).
    """

    async def send_text(self, channel_id: str, speaker: Speaker, text: str) -> str: ...

    async def send_image(self, channel_id: str, speaker: Speaker, image: ImagePart) -> str: ...

    async def set_typing(self, channel_id: str, speaker: Speaker, on: bool) -> None: ...

    async def notify_interrupted(self, channel_id: str, speaker: Speaker) -> None: ...


@dataclass(frozen=True)
class InboundMessage:
    """A turn arriving from a human (or upstream) into a channel.

    ``speaker_id`` is the platform-neutral id of the sender; ``client_ts`` is an
    optional client-supplied timestamp (ISO string) used for ordering/debounce.
    """

    channel_id: str
    speaker_id: str
    text: str
    images: tuple[ImagePart, ...] = ()
    client_ts: str = ""


@runtime_checkable
class Inbox(Protocol):
    """Source the kernel reads inbound turns from.

    An adapter calls ``on_message`` for each inbound turn; the dispatcher then
    routes it (e.g. into ``generate_response_streaming``).
    """

    async def on_message(self, msg: InboundMessage) -> None: ...
