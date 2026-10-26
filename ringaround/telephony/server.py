"""
Telnyx webhook + WebSocket server (FastAPI).

Lifecycle:
  1. Telnyx POSTs call events to POST /webhook
  2. On call.answered  → POST /v2/calls/{id}/actions/streaming_start
  3. Telnyx opens WS  → GET  /stream/{call_control_id}
  4. TelnyxCallSession is live; dial() future resolves

The module-level _REGISTRY maps call_control_id →
  {"future": asyncio.Future, "session": TelnyxCallSession | None}
"""
from __future__ import annotations
import asyncio
import base64
import logging
import os
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from ringaround.telephony.telnyx import TelnyxCallSession

log = logging.getLogger(__name__)

# call_control_id → {"future": Future, "session": TelnyxCallSession | None}
_REGISTRY: dict[str, dict] = {}


def register_call(call_control_id: str, future: asyncio.Future) -> None:
    _REGISTRY[call_control_id] = {"future": future, "session": None}


def _resolve(call_control_id: str, session) -> None:
    entry = _REGISTRY.get(call_control_id)
    if entry and not entry["future"].done():
        entry["session"] = session
        entry["future"].set_result(session)


def _reject(call_control_id: str, reason: str) -> None:
    entry = _REGISTRY.get(call_control_id)
    if entry and not entry["future"].done():
        entry["future"].set_exception(RuntimeError(reason))


async def _start_streaming(call_control_id: str, stream_url: str) -> None:
    api_key = os.environ["TELNYX_API_KEY"]
    url = f"https://api.telnyx.com/v2/calls/{call_control_id}/actions/streaming_start"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            url,
            json={"stream_url": stream_url, "stream_track": "both_tracks"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if resp.status_code not in (200, 202):
            log.warning("streaming_start failed %s: %s", resp.status_code, resp.text)


def create_app(stream_ws_base: str):
    """
    Build and return the FastAPI app.

    stream_ws_base: e.g. "wss://abc.ngrok.io"
    """
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
        from fastapi.responses import JSONResponse
    except ImportError as e:
        raise ImportError(
            "FastAPI is required for Telnyx. Install with: uv pip install 'ringaround[telnyx]'"
        ) from e

    from ringaround.telephony.telnyx import TelnyxCallSession

    app = FastAPI(title="RingAround Telnyx Server")

    @app.post("/webhook")
    async def webhook(request: Request):
        body = await request.json()
        data = body.get("data", {})
        event_type = data.get("event_type", "")
        payload = data.get("payload", {})
        call_control_id = payload.get("call_control_id", "")

        if event_type == "call.answered":
            ws_url = f"{stream_ws_base}/stream/{call_control_id}"
            asyncio.create_task(_start_streaming(call_control_id, ws_url))

        elif event_type in ("call.hangup", "call.failed"):
            _reject(call_control_id, event_type)

        return JSONResponse({"ok": True})

    @app.websocket("/stream/{call_control_id}")
    async def media_stream(ws: WebSocket, call_control_id: str):
        await ws.accept()
        session = TelnyxCallSession(call_control_id, ws)
        _resolve(call_control_id, session)

        try:
            while True:
                msg = await ws.receive_json()
                event = msg.get("event")

                if event == "media":
                    track = msg.get("media", {}).get("track", "")
                    if track == "inbound":
                        raw = base64.b64decode(msg["media"]["payload"])
                        await session._inbound.put(raw)

                elif event == "stop":
                    break

        except (WebSocketDisconnect, Exception):
            pass
        finally:
            _reject(call_control_id, "websocket closed")

    return app
