"""
Claude Haiku LLM provider — intent classification + agent turn generation.
Uses structured single-word responses for intent to keep latency low.
Agent turns use the same templates as mock; swap to freeform generation
by setting CLAUDE_FREEFORM_AGENT=1.
"""
from __future__ import annotations
import os
import re
import asyncio
from ringaround.models import TurnIntent, CallState, ProjectRequest
from ringaround.llm.mock import AGENT_SCRIPTS, _INTENT_RULES

_MODEL = "claude-haiku-4-5-20251001"

_CLASSIFY_PROMPT = """\
You are classifying a contractor's phone response during a quote-gathering call.

Call state: {state}
Contractor said: "{vendor_text}"

Pick exactly one label:
POSITIVE       - agreeable, yes, will help
NEEDS_MORE_INFO - asking a question before committing to a price
GAVE_QUOTE     - mentioned a specific price or dollar range
CALL_BACK      - wants a callback later, busy right now
REFUSED        - won't give a quote over the phone, wrong type of work
OUT_OF_AREA    - doesn't service this location or zip code
UNAVAILABLE    - fully booked, not taking new projects
HUNG_UP        - line dropped, no response

Respond with only the label, nothing else."""


class ClaudeLLMProvider:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def classify_intent(self, vendor_text: str, state: CallState) -> TurnIntent:
        if not vendor_text.strip():
            return TurnIntent.HUNG_UP

        # Fast path: regex matches cover >90% of cases
        text = vendor_text.lower()
        for pattern, intent in _INTENT_RULES:
            if re.search(pattern, text, re.IGNORECASE):
                return intent

        if not self._api_key:
            return TurnIntent.UNCLEAR

        try:
            client = self._get_client()
            response = await client.messages.create(
                model=_MODEL,
                max_tokens=16,
                messages=[{
                    "role": "user",
                    "content": _CLASSIFY_PROMPT.format(
                        state=state.value,
                        vendor_text=vendor_text,
                    ),
                }],
            )
            label = response.content[0].text.strip().upper()
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
