"""
Gemini Flash LLM provider — intent classification via REST (no extra SDK dep).
Uses httpx; GEMINI_API_KEY must be set. Falls back to regex on failure.
"""
from __future__ import annotations
import os
import re
import json
import httpx
from ringaround.models import TurnIntent, CallState, ProjectRequest
from ringaround.llm.mock import AGENT_SCRIPTS, _INTENT_RULES

_MODEL = "gemini-2.0-flash-exp"
_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_CLASSIFY_PROMPT = """\
Classify this contractor's phone response. Call state: {state}.
Contractor said: "{vendor_text}"

Reply with exactly one of these words only:
POSITIVE NEEDS_MORE_INFO GAVE_QUOTE CALL_BACK REFUSED OUT_OF_AREA UNAVAILABLE HUNG_UP UNCLEAR"""


class GeminiLLMProvider:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")

    async def classify_intent(self, vendor_text: str, state: CallState) -> TurnIntent:
        if not vendor_text.strip():
            return TurnIntent.HUNG_UP

        # Fast path: regex first
        text = vendor_text.lower()
        for pattern, intent in _INTENT_RULES:
            if re.search(pattern, text, re.IGNORECASE):
                return intent

        if not self._api_key:
            return TurnIntent.UNCLEAR

        try:
            url = f"{_BASE_URL}/{_MODEL}:generateContent?key={self._api_key}"
            payload = {
                "contents": [{"parts": [{"text": _CLASSIFY_PROMPT.format(
                    state=state.value,
                    vendor_text=vendor_text,
                )}]}],
                "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                label = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
                return TurnIntent(label.lower()) if label.lower() in TurnIntent._value2member_map_ else TurnIntent.UNCLEAR
        except Exception:
            return TurnIntent.UNCLEAR

    async def generate_agent_turn(
        self, state: CallState, project: ProjectRequest, context: dict
    ) -> str:
        template = AGENT_SCRIPTS.get(state, "Thank you, goodbye.")
        return template.format(
            description=project.description,
            zip_code=project.zip_code,
        )
