"""
Concurrent job runner. Dials up to MAX_CONCURRENT_CALLS simultaneously,
collects results, runs quote extraction on completed calls.
"""
from __future__ import annotations
import asyncio
import os
from datetime import datetime
from ringaround.models import Job, CallResult, Contractor, ProjectRequest
from ringaround.agent.call_flow import CallFlow


async def run_job(
    job: Job,
    call_flow: CallFlow,
    max_concurrent: int | None = None,
) -> Job:
    if max_concurrent is None:
        max_concurrent = int(os.getenv("MAX_CONCURRENT_CALLS", "10"))

    sem = asyncio.Semaphore(max_concurrent)

    async def dial_one(contractor: Contractor) -> CallResult:
        async with sem:
            return await call_flow.run(contractor, job.project, job.id)

    tasks = [dial_one(c) for c in job.contractors]
    results: list[CallResult] = await asyncio.gather(*tasks)
    # Extraction already ran inside CallFlow.run() per call

    job.results = list(results)
    job.completed_at = datetime.utcnow()
    return job


def summarize_job(job: Job) -> dict:
    total = len(job.results)
    quotes = job.quotes
    ranked = job.ranked_quotes

    summary: dict = {
        "job_id": job.id,
        "total_calls": total,
        "answered": sum(1 for r in job.results if r.final_state.value not in ("no_answer", "failed")),
        "quotes_received": len(quotes),
        "refused": sum(1 for r in job.results if r.final_state.value == "refused"),
        "unavailable": sum(1 for r in job.results if r.final_state.value == "unavailable"),
        "no_answer": sum(1 for r in job.results if r.final_state.value == "no_answer"),
        "callback_scheduled": sum(1 for r in job.results if r.final_state.value == "callback_scheduled"),
        "out_of_area": sum(1 for r in job.results if r.final_state.value == "out_of_area"),
        "ranked_quotes": [],
    }

    for r in ranked:
        summary["ranked_quotes"].append({
            "contractor": r.contractor.name,
            "price_low": r.quote.price_low,
            "price_high": r.quote.price_high,
            "availability": r.quote.availability,
            "timeline_weeks": r.quote.timeline_weeks,
            "confidence": r.quote.confidence,
        })

    if quotes:
        prices = [q.quote.price_low for q in quotes if q.quote and q.quote.price_low]
        if prices:
            summary["market_low"] = min(prices)
            summary["market_high"] = max(prices)
            summary["market_median"] = sorted(prices)[len(prices) // 2]

    return summary
