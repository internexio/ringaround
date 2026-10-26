from typing import Protocol


class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> bytes:
        """Convert text to PCM audio bytes."""
        ...
