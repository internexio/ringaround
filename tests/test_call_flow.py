"""
Tests covering all six mock vendor personas end-to-end.
No real API calls — fully local, fast.
"""
import pytest
from ringaround.models import (
    CallState, Contractor, ProjectRequest, Job,
)
from ringaround.telephony.mock import MockTelephonyProvider
from ringaround.audio.stt.mock import MockSTTProvider
from ringaround.audio.tts.mock import MockTTSProvider
from ringaround.llm.mock import MockLLMProvider
from ringaround.agent.call_flow import CallFlow
from ringaround.jobs.runner import run_job, summarize_job


def make_flow() -> CallFlow:
    return CallFlow(
        telephony=MockTelephonyProvider(),
        stt=MockSTTProvider(),
        tts=MockTTSProvider(),
        llm=MockLLMProvider(),
    )


def make_contractor(name: str, persona: str) -> Contractor:
    return Contractor(
        name=name, phone="206-555-0100", zip_code="98103",
        category="bathroom_remodel", mock_persona=persona,
    )


PROJECT = ProjectRequest(
    description="full bathroom remodel, approximately 80 square feet, existing plumbing to stay",
    zip_code="98103",
    category="bathroom_remodel",
)


@pytest.mark.asyncio
async def test_quick_quoter_completes_with_quote():
    flow = make_flow()
    contractor = make_contractor("Quick Bath Co", "quick_quoter")
    result = await flow.run(contractor, PROJECT, "job-1")

    assert result.final_state == CallState.COMPLETED
    assert result.quote is not None
    assert result.quote.price_low is not None
    assert result.quote.price_low >= 1000
    assert len(result.turns) >= 3


@pytest.mark.asyncio
async def test_unavailable_no_answer():
    flow = make_flow()
    contractor = make_contractor("Ghost Plumbing", "unavailable")
    result = await flow.run(contractor, PROJECT, "job-1")

    assert result.final_state == CallState.NO_ANSWER
    assert len(result.turns) == 0


@pytest.mark.asyncio
async def test_too_busy_schedules_callback():
    flow = make_flow()
    contractor = make_contractor("Busy Builders", "too_busy")
    result = await flow.run(contractor, PROJECT, "job-1")

    assert result.final_state == CallState.CALLBACK_SCHEDULED


@pytest.mark.asyncio
async def test_refused_exits_early():
    flow = make_flow()
    contractor = make_contractor("No Phone Quotes LLC", "refused")
    result = await flow.run(contractor, PROJECT, "job-1")

    assert result.final_state == CallState.REFUSED
    assert len(result.turns) >= 1


@pytest.mark.asyncio
async def test_chatty_still_produces_quote():
    flow = make_flow()
    contractor = make_contractor("Chatty Renovations", "chatty")
    result = await flow.run(contractor, PROJECT, "job-1")

    assert result.final_state == CallState.COMPLETED
    assert result.got_quote


@pytest.mark.asyncio
async def test_out_of_area_exits():
    flow = make_flow()
    contractor = make_contractor("Far Away Tiles", "out_of_area")
    result = await flow.run(contractor, PROJECT, "job-1")

    assert result.final_state == CallState.OUT_OF_AREA


@pytest.mark.asyncio
async def test_job_runner_concurrent():
    personas = [
        ("Quick Bath Co", "quick_quoter"),
        ("Ghost Plumbing", "unavailable"),
        ("Busy Builders", "too_busy"),
        ("No Phone Quotes LLC", "refused"),
        ("Chatty Renovations", "chatty"),
        ("Far Away Tiles", "out_of_area"),
    ]
    contractors = [make_contractor(name, p) for name, p in personas]
    job = Job(project=PROJECT, contractors=contractors)

    completed = await run_job(job, make_flow(), max_concurrent=6)

    assert completed.completed_at is not None
    assert len(completed.results) == 6
    assert len(completed.quotes) >= 2  # quick_quoter + chatty


@pytest.mark.asyncio
async def test_job_summary_structure():
    contractors = [
        make_contractor("Quick Bath Co", "quick_quoter"),
        make_contractor("Chatty Renovations", "chatty"),
        make_contractor("Ghost Plumbing", "unavailable"),
    ]
    job = Job(project=PROJECT, contractors=contractors)
    completed = await run_job(job, make_flow(), max_concurrent=3)
    summary = summarize_job(completed)

    assert summary["total_calls"] == 3
    assert summary["quotes_received"] >= 1
    assert "ranked_quotes" in summary
    if summary["quotes_received"] > 0:
        assert "market_low" in summary
        assert summary["market_low"] <= summary["market_high"]


@pytest.mark.asyncio
async def test_ranked_quotes_ordered_ascending():
    contractors = [make_contractor(f"Contractor {i}", "quick_quoter") for i in range(3)]
    job = Job(project=PROJECT, contractors=contractors)
    completed = await run_job(job, make_flow(), max_concurrent=3)

    prices = [r.quote.price_low for r in completed.ranked_quotes if r.quote and r.quote.price_low]
    assert prices == sorted(prices)
