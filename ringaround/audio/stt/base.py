from typing import Protocol


class STTProvider(Protocol):
    async def transcribe_turn(self, audio_bytes: bytes, hint: str = "") -> str:
        """Convert one turn's audio to text. Returns empty string on silence."""
        ...
