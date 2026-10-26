from __future__ import annotations
from typing import Protocol, AsyncIterator
from ringaround.models import CallState


class CallSession(Protocol):
    """Live call handle — send audio, receive audio, hang up."""
    call_id: str

    async def send_audio(self, pcm_bytes: bytes) -> None: ...
    async def receive_audio(self) -> AsyncIterator[bytes]: ...
    async def hang_up(self) -> None: ...


class TelephonyProvider(Protocol):
    async def dial(self, phone: str, context: dict) -> CallSession: ...
