"""
Deepgram Nova-2 STT provider.
Sends raw PCM (16kHz mono 16-bit) to Deepgram's prerecorded endpoint.
Returns empty string on silence or error.
"""
from __future__ import annotations
import os
import httpx

_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_DEFAULT_PARAMS = {
    "model": "nova-2",
    "encoding": "linear16",
    "sample_rate": "16000",
    "channels": "1",
    "punctuate": "true",
    "utterances": "false",
}


class DeepgramSTTProvider:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("DEEPGRAM_API_KEY")

    async def transcribe_turn(self, audio_bytes: bytes, hint: str = "") -> str:
        if not audio_bytes or not self._api_key:
            return ""

        # Skip near-silent chunks (< 0.1s at 16kHz/16-bit = 3200 bytes)
        if len(audio_bytes) < 3200:
            return ""

        try:
            headers = {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "audio/raw",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _DEEPGRAM_URL,
                    params=_DEFAULT_PARAMS,
                    headers=headers,
                    content=audio_bytes,
                )
                resp.raise_for_status()
                data = resp.json()
                channels = data.get("results", {}).get("channels", [])
                if not channels:
                    return ""
                alts = channels[0].get("alternatives", [])
                if not alts:
                    return ""
                return alts[0].get("transcript", "").strip()
        except Exception:
            return ""
