"""
Cartesia Sonic TTS provider.
Returns raw PCM bytes (16kHz mono 16-bit) suitable for telephony.
Voice: sonic-english, output format: pcm_s16le / 16000 Hz.
"""
from __future__ import annotations
import os
import httpx

_CARTESIA_URL = "https://api.cartesia.ai/tts/bytes"
_VOICE_ID = "a0e99841-438c-4a64-b679-ae501e7d6091"  # Sonic English neutral


class CartesiaTTSProvider:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("CARTESIA_API_KEY")

    async def synthesize(self, text: str) -> bytes:
        if not text.strip() or not self._api_key:
            return b""

        payload = {
            "model_id": "sonic-english",
            "transcript": text,
            "voice": {"mode": "id", "id": _VOICE_ID},
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": 16000,
            },
        }
        headers = {
            "X-API-Key": self._api_key,
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(_CARTESIA_URL, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.content
        except Exception:
            return b""
