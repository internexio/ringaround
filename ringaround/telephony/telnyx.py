"""
Telnyx telephony provider.

Env vars required:
  TELNYX_API_KEY         — Bearer token
  TELNYX_CONNECTION_ID   — SIP connection / TeXML app ID
  TELNYX_FROM_NUMBER     — E.164 caller ID (your Telnyx DID)
  TELNYX_PUBLIC_URL      — public HTTPS base (e.g. https://abc.ngrok.io)
  TELNYX_APP_PORT        — local port for the server (default 8080)

Audio: Telnyx delivers PCMU 8kHz over WebSocket.
  Inbound  → ulaw_to_pcm16 → Deepgram (or pass raw PCMU with encoding hint)
  Outbound → Cartesia 16kHz PCM → downsample_2x → pcm16_to_ulaw → base64
"""
from __future__ import annotations
import asyncio
import base64
import os
import httpx
from ringaround.audio.codec import pcm16_to_ulaw, downsample_2x, ulaw_to_pcm16
from ringaround.telephony.server import register_call

_TELNYX_API = "https://api.telnyx.com/v2"
_DIAL_TIMEOUT = 60  # seconds to wait for call to be answered


class TelnyxCallSession:
    """Live call handle backed by a Telnyx media streaming WebSocket."""

    def __init__(self, call_control_id: str, ws):
        self.call_id = call_control_id
        self._ws = ws
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Send 16kHz PCM → downsample → µ-law → base64 → Telnyx."""
        if not pcm_bytes:
            return
        pcm8k = downsample_2x(pcm_bytes)
        ulaw = pcm16_to_ulaw(pcm8k)
        payload = base64.b64encode(ulaw).decode()
        await self._ws.send_json({
            "event": "media",
            "media": {"payload": payload},
        })

    async def receive_audio(self):
        """Yield inbound µ-law chunks decoded to 8kHz PCM."""
        while True:
            chunk = await self._inbound.get()
            yield ulaw_to_pcm16(chunk)

    async def hang_up(self) -> None:
        api_key = os.environ.get("TELNYX_API_KEY", "")
        if not api_key:
            return
        url = f"{_TELNYX_API}/calls/{self.call_id}/actions/hangup"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    url,
                    json={},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except Exception:
            pass


class TelnyxProvider:
    """Initiates outbound calls via Telnyx Call Control API."""

    def __init__(self):
        self._api_key = os.environ.get("TELNYX_API_KEY", "")
        self._connection_id = os.environ.get("TELNYX_CONNECTION_ID", "")
        self._from_number = os.environ.get("TELNYX_FROM_NUMBER", "")
        self._public_url = os.environ.get("TELNYX_PUBLIC_URL", "").rstrip("/")

    async def dial(self, phone: str, context: dict) -> TelnyxCallSession | None:
        """
        Initiate an outbound call and wait for the media WebSocket to open.

        Returns a TelnyxCallSession when the call is answered and streaming
        begins, or None if the call is not answered within DIAL_TIMEOUT.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        # POST to create the call
        payload = {
            "connection_id": self._connection_id,
            "to": phone,
            "from": self._from_number,
            "webhook_url": f"{self._public_url}/webhook",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{_TELNYX_API}/calls",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                resp.raise_for_status()
                call_control_id = resp.json()["data"]["call_control_id"]
        except Exception:
            return None

        # Register Future so the server can resolve it when WebSocket opens
        register_call(call_control_id, future)

        try:
            session = await asyncio.wait_for(future, timeout=_DIAL_TIMEOUT)
            return session
        except (asyncio.TimeoutError, RuntimeError):
            return None
