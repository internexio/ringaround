"""
Mock STT — returns scripted vendor utterances based on persona and call state.
Each persona has a response sequence per call state; after exhausting the
sequence it returns a polite closing line.
"""
from __future__ import annotations
import asyncio
from ringaround.models import CallState

# persona → state → [utterance sequence]
SCRIPTS: dict[str, dict[str, list[str]]] = {
    "quick_quoter": {
        "intro": ["Sure, I can help with that. What's the project?"],
        "confirm_project": ["Yeah, full bathroom remodel, got it."],
        "quote_ask": ["For that size, I'd say somewhere between $12,000 and $16,000."],
        "follow_up": [
            "We're available starting in about 3 weeks.",
            "You can reach us directly at the same number.",
        ],
        "close": ["Sounds good, have them give us a call."],
    },
    "too_busy": {
        "intro": ["Yeah hi, we're actually slammed right now. Can you call back tomorrow morning?"],
    },
    "refused": {
        "intro": ["We don't give quotes over the phone, sorry. You'd need to schedule an in-home estimate."],
    },
    "out_of_area": {
        "intro": ["Sure, what area is the project?"],
        "confirm_project": ["Oh, we don't actually service that zip code, sorry."],
    },
    "chatty": {
        "intro": [
            "Oh yeah, we do bathroom remodels. We've been doing this for about twenty years now. "
            "My father started the business back in 2003. What kind of project are we talking?"
        ],
        "confirm_project": [
            "Eighty square feet, okay. Is that with a tub or just a walk-in shower? "
            "Because that makes a big difference on the tile work."
        ],
        "quote_ask": [
            "Hmm, it really depends on the fixtures. Mid-range I'd say $14,000 to $18,000. "
            "High-end could push it to $25,000. What's their budget situation?"
        ],
        "follow_up": [
            "We could probably start in about a month.",
            "Yeah ask them to call us and we'll set up a walkthrough.",
        ],
        "close": ["Alright, hope to hear from them!"],
    },
    "unavailable": {},
}


class MockSTTProvider:
    def __init__(self):
        self._counters: dict[str, int] = {}

    async def transcribe_turn(self, audio_bytes: bytes, hint: str = "") -> str:
        await asyncio.sleep(0.05)  # simulate processing

        # hint format: "persona:state"
        parts = hint.split(":")
        if len(parts) != 2:
            return ""
        persona, state = parts[0], parts[1]

        script = SCRIPTS.get(persona, {}).get(state, [])
        key = f"{persona}:{state}"
        idx = self._counters.get(key, 0)

        if idx >= len(script):
            return ""  # silence / end of script

        self._counters[key] = idx + 1
        return script[idx]
