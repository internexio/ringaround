"""
Tests for real LLM providers — covers regex fast-path and no-key fallback.
These run fully offline; they do NOT hit any external API.
"""
from __future__ import annotations
import pytest
from ringaround.models import TurnIntent, CallState, ProjectRequest
from ringaround.llm.claude import ClaudeLLMProvider
from ringaround.llm.gemini import GeminiLLMProvider
from ringaround.factory import build_call_flow


PROJECT = ProjectRequest(
    description="full bathroom remodel, 80 sq ft",
    zip_code="98101",
    category="bathroom_remodel",
)

_PROVIDERS = [
    ClaudeLLMProvider(api_key=None),
    GeminiLLMProvider(api_key=None),
]


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_classify_positive(provider):
    intent = await provider.classify_intent("Sure, I can help with that.", CallState.INTRO)
    assert intent == TurnIntent.POSITIVE


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_classify_gave_quote(provider):
    intent = await provider.classify_intent(
        "For that size, I'd say $12,000 to $16,000.", CallState.QUOTE_ASK
    )
    assert intent == TurnIntent.GAVE_QUOTE


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_classify_refused(provider):
    intent = await provider.classify_intent(
        "We don't give quotes over the phone.", CallState.INTRO
    )
    assert intent == TurnIntent.REFUSED


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_classify_callback(provider):
    intent = await provider.classify_intent(
        "We're slammed right now, call back tomorrow.", CallState.INTRO
    )
    assert intent == TurnIntent.CALL_BACK


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_classify_out_of_area(provider):
    intent = await provider.classify_intent(
        "We don't actually service that zip code.", CallState.CONFIRM_PROJECT
    )
    assert intent == TurnIntent.OUT_OF_AREA


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_classify_unavailable(provider):
    intent = await provider.classify_intent(
        "We're not taking any new projects right now.", CallState.INTRO
    )
    assert intent == TurnIntent.UNAVAILABLE


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_classify_empty_is_hung_up(provider):
    intent = await provider.classify_intent("", CallState.INTRO)
    assert intent == TurnIntent.HUNG_UP


@pytest.mark.parametrize("provider", _PROVIDERS)
async def test_agent_turn_contains_zip(provider):
    text = await provider.generate_agent_turn(CallState.CONFIRM_PROJECT, PROJECT, {})
    assert "98101" in text
    assert "bathroom" in text.lower()


def test_factory_builds_mock_stack():
    flow = build_call_flow()
    assert flow is not None
