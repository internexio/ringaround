"""
Post-call quote extractor. Runs after each completed call.
Uses real LLM (Claude Haiku) — this is where extraction quality matters.
Falls back gracefully if API key not set (returns empty Quote).
"""
from __future__ import annotations
import json
import os
from ringaround.models import CallResult, Quote, CallState


EXTRACTION_PROMPT = """You are extracting structured quote information from a phone call transcript.

The call was between an automated agent (A) and a contractor (V) about a home improvement project.

Transcript:
{transcript}

Extract the following as JSON. Use null for any field not mentioned.
- price_low: integer USD (lowest price mentioned, e.g. 12000)
- price_high: integer USD (highest price mentioned, e.g. 16000)
- availability: "available" | "unavailable" | "unknown"
- timeline_weeks: integer (how many weeks until they can start, null if not mentioned)
- license_mentioned: boolean (did they mention being licensed/bonded/insured?)
- callback_requested: boolean (did they ask to be called back?)
- confidence: float 0.0-1.0 (how confident are you in this extraction?)
- raw_quote_text: string (verbatim text where the price was mentioned, or "" if none)

Respond with only valid JSON, no commentary."""


def _build_transcript(result: CallResult) -> str:
    lines = []
    for turn in result.turns:
        lines.append(f"A: {turn.agent_text}")
        if turn.vendor_text:
            lines.append(f"V: {turn.vendor_text}")
    return "\n".join(lines)


async def extract_quote(result: CallResult) -> Quote:
    if result.final_state != CallState.COMPLETED:
        return Quote()

    transcript = _build_transcript(result)
    if not transcript.strip():
        return Quote()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_extract(transcript)

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": EXTRACTION_PROMPT.format(transcript=transcript),
            }],
        )
        text = response.content[0].text.strip()
        data = json.loads(text)
        return Quote(**{k: v for k, v in data.items() if k in Quote.model_fields})
    except Exception:
        return _fallback_extract(transcript)


def _fallback_extract(transcript: str) -> Quote:
    """Regex-based fallback when no API key is set."""
    import re
    quote = Quote()

    amounts = []
    for m in re.finditer(r'\$\s*([\d,]+(?:\.\d+)?)\s*(?:thousand|k\b)?', transcript, re.IGNORECASE):
        try:
            v = float(m.group(1).replace(",", ""))
            if 500 <= v <= 500_000:
                amounts.append(int(v))
        except ValueError:
            pass
    for m in re.finditer(r'\b(\d[\d,]*)\s*(?:thousand|k)\b', transcript, re.IGNORECASE):
        try:
            v = float(m.group(1).replace(",", "")) * 1000
            if 500 <= v <= 500_000:
                amounts.append(int(v))
        except ValueError:
            pass

    if amounts:
        quote.price_low = min(amounts)
        quote.price_high = max(amounts)
        quote.confidence = 0.6
        quote.raw_quote_text = transcript[:200]

    if re.search(r'\bavailable\b|\bcan (start|take|do)\b', transcript, re.I):
        quote.availability = "available"
    elif re.search(r'\bnot available\b|\bfully booked\b', transcript, re.I):
        quote.availability = "unavailable"

    weeks = re.search(r'(\d+)\s+weeks?', transcript, re.I)
    if weeks:
        quote.timeline_weeks = int(weeks.group(1))

    return quote
