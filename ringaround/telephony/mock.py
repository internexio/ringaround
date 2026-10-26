"""
Mock telephony — simulates call connection/disconnection with vendor personas.
Personas drive what the STT mock returns; telephony mock only signals
answer/no-answer/busy.
"""
from __future__ import annotations
import asyncio
import uuid
from typing import AsyncIterator
from ringaround.models import Contractor


class MockCallSession:
    def __init__(self, call_id: str, persona: str):
        self.call_id = call_id
        self.persona = persona
        self._hung_up = False

    async def send_audio(self, pcm_bytes: bytes) -> None:
        await asyncio.sleep(0)  # yield to event loop

    async def receive_audio(self) -> AsyncIterator[bytes]:
        # Mock: yield silence chunks until hung up
        while not self._hung_up:
            await asyncio.sleep(0.1)
            yield b"\x00" * 3200  # 100ms of silence at 16kHz 16-bit mono

    async def hang_up(self) -> None:
        self._hung_up = True


PERSONA_ANSWER_DELAY = {
    "quick_quoter":   0.5,
    "unavailable":    None,   # None = no answer
    "too_busy":       0.8,
    "refused":        0.6,
    "chatty":         1.0,
    "out_of_area":    0.7,
}


class MockTelephonyProvider:
    """
    Assigns personas round-robin for predictable test coverage.
    In real usage, persona comes from the contractor record (for testing)
    or defaults to 'quick_quoter'.
    """

    async def dial(self, phone: str, context: dict) -> MockCallSession | None:
        persona = context.get("mock_persona", "quick_quoter")
        delay = PERSONA_ANSWER_DELAY.get(persona)

        if delay is None:
            await asyncio.sleep(0.2)
            return None  # no answer

        await asyncio.sleep(delay)
        return MockCallSession(call_id=str(uuid.uuid4()), persona=persona)
