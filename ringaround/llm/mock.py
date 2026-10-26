"""
Mock LLM — keyword-based intent classification and scripted agent utterances.
Fast, free, deterministic. Real LLM provider swaps in via env var.
"""
from __future__ import annotations
import asyncio
import re
from ringaround.models import TurnIntent, CallState, ProjectRequest

_INTENT_RULES: list[tuple[str, TurnIntent]] = [
    (r"\b(call back|tomorrow|later|not a good time|busy)\b", TurnIntent.CALL_BACK),
    (r"\b(don.t\b.{0,20}\bservice|out of (your |our )?area|don.t cover|not our area|don.t (work|operate) (in|there)|zip code)\b", TurnIntent.OUT_OF_AREA),
    (r"\b(not available|fully booked|no availability|can.t take|not taking)\b", TurnIntent.UNAVAILABLE),
    (r"\b(don.t (do|give) (quotes?|estimates?) over (the )?phone|need (to|an) (come|in-home|on-site))\b", TurnIntent.REFUSED),
    (r"\$[\d,]+|\b\d{1,3}(,\d{3})*\b.{0,20}\b(thousand|k)\b|\b(between|from|around|about).{0,30}\band\b", TurnIntent.GAVE_QUOTE),
    (r"\b(what (kind|type|size)|more (info|detail)|which|how (big|many|much))\b", TurnIntent.NEEDS_MORE_INFO),
    (r"\b(sure|yeah|yes|go ahead|okay|of course|happy to|absolutely)\b", TurnIntent.POSITIVE),
]

AGENT_SCRIPTS: dict[CallState, str] = {
    CallState.INTRO: (
        "Hi, this is an automated service calling on behalf of a homeowner. "
        "I'm gathering quotes for a home improvement project. Is this a good time?"
    ),
    CallState.CONFIRM_PROJECT: (
        "Great. The project is {description}, located in zip code {zip_code}. "
        "The homeowner is hoping to start in the next six to eight weeks. Does that sound like something you'd take on?"
    ),
    CallState.QUOTE_ASK: (
        "Could you give me a rough ballpark range for that project? "
        "Just a low and high estimate is fine."
    ),
    CallState.FOLLOW_UP: (
        "And roughly when would your team be available to start? "
        "Also, is there a direct number for the homeowner to reach you?"
    ),
    CallState.CLOSE: (
        "Perfect. I'll pass this along to the homeowner. Thank you so much for your time."
    ),
}


class MockLLMProvider:
    async def classify_intent(self, vendor_text: str, state: CallState) -> TurnIntent:
        await asyncio.sleep(0.01)
        if not vendor_text.strip():
            return TurnIntent.HUNG_UP
        text = vendor_text.lower()
        for pattern, intent in _INTENT_RULES:
            if re.search(pattern, text, re.IGNORECASE):
                return intent
        return TurnIntent.UNCLEAR

    async def generate_agent_turn(
        self, state: CallState, project: ProjectRequest, context: dict
    ) -> str:
        await asyncio.sleep(0.01)
        template = AGENT_SCRIPTS.get(state, "Thank you, goodbye.")
        return template.format(
            description=project.description,
            zip_code=project.zip_code,
        )
