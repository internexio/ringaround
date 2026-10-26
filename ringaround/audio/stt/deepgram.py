"""
Deepgram Nova-2 STT provider.
Sends raw PCM (16kHz mono 16-bit) to Deepgram's prerecorded endpoint.
Returns empty string on silence or error.
"""
from __future__ import annotations
import os
import httpx

_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_BASE_PARAMS = {
    "model": "nova-2",
    "channels": "1",
    "punctuate": "true",
    "utterances": "false",
}

# Minimum bytes for a 0.1s utterance at given sample rates
_MIN_BYTES = {8000: 1600, 16000: 3200}


class DeepgramSTTProvider:
    def __init__(
        self,
        api_key: str | None = None,
        sample_rate: int = 16000,
        encoding: str = "linear16",
    ):
        self._api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        self._params = {
            **_BASE_PARAMS,
            "encoding": encoding,
            "sample_rate": str(sample_rate),
        }
        self._min_bytes = _MIN_BYTES.get(sample_rate, 3200)

    async def transcribe_turn(self, audio_bytes: bytes, hint: str = "") -> str:
        if not audio_bytes or not self._api_key:
            return ""

        if len(audio_bytes) < self._min_bytes:
            return ""

        try:
            headers = {
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "audio/raw",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    _DEEPGRAM_URL,
                    params=self._params,
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
