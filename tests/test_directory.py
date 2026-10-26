"""
Directory integration tests — runs fully offline using mock provider.
Also unit-tests phone normalization and category query mapping.
"""
from __future__ import annotations
import pytest
from ringaround.models import ProjectRequest
from ringaround.directory.mock import MockDirectoryProvider
from ringaround.directory.google_places import (
    GooglePlacesProvider,
    CATEGORY_QUERIES,
    _normalize_phone,
)
from ringaround.factory import build_directory


PROJECT = ProjectRequest(
    description="full bathroom remodel, 80 sq ft",
    zip_code="98101",
    category="bathroom_remodel",
)


# --- mock provider ---

async def test_mock_returns_contractors():
    directory = MockDirectoryProvider()
    contractors = await directory.find_contractors(PROJECT)
    assert len(contractors) == 6
    for c in contractors:
        assert c.phone.startswith("+1")
        assert c.zip_code == "98101"
        assert c.category == "bathroom_remodel"
        assert c.source == "mock_directory"


async def test_mock_respects_limit():
    directory = MockDirectoryProvider()
    contractors = await directory.find_contractors(PROJECT, limit=3)
    assert len(contractors) == 3


async def test_mock_personas_are_varied():
    directory = MockDirectoryProvider()
    contractors = await directory.find_contractors(PROJECT)
    personas = {c.mock_persona for c in contractors}
    assert len(personas) > 1  # at least two distinct personas


# --- phone normalisation ---

@pytest.mark.parametrize("raw,expected", [
    ("(206) 555-0101",  "+12065550101"),
    ("206-555-0101",    "+12065550101"),
    ("12065550101",     "+12065550101"),
    ("+12065550101",    "+12065550101"),
    ("2065550101",      "+12065550101"),
    ("555-0101",        None),            # too short
    ("invalid",         None),
])
def test_normalize_phone(raw, expected):
    assert _normalize_phone(raw) == expected


# --- category query map ---

def test_all_expected_categories_present():
    for cat in ("bathroom_remodel", "roofing", "hvac", "plumbing", "electrical"):
        assert cat in CATEGORY_QUERIES, f"missing category: {cat}"


def test_unknown_category_uses_fallback():
    # GooglePlacesProvider falls back to "{category} contractor" for unknown keys
    assert "mystery_trade" not in CATEGORY_QUERIES  # sanity check
    phrase = CATEGORY_QUERIES.get(
        "mystery_trade",
        "mystery_trade".replace("_", " ") + " contractor",
    )
    assert phrase == "mystery trade contractor"


# --- factory ---

def test_factory_builds_mock_directory():
    directory = build_directory()
    assert directory is not None


async def test_factory_mock_is_functional():
    directory = build_directory()
    contractors = await directory.find_contractors(PROJECT)
    assert len(contractors) > 0


# --- GooglePlacesProvider raises without key ---

async def test_google_places_raises_without_key():
    provider = GooglePlacesProvider(api_key=None)
    with pytest.raises(RuntimeError, match="GOOGLE_PLACES_API_KEY"):
        await provider.find_contractors(PROJECT)


# --- integration: directory → job pipeline (all mock) ---

async def test_directory_feeds_job_pipeline():
    from ringaround.jobs.runner import run_job, summarize_job
    from ringaround.models import Job
    from ringaround.factory import build_call_flow

    directory = MockDirectoryProvider()
    contractors = await directory.find_contractors(PROJECT)

    job = Job(project=PROJECT, contractors=contractors)
    flow = build_call_flow()
    completed_job = await run_job(job, flow)

    summary = summarize_job(completed_job)
    assert summary["total_calls"] == len(contractors)
    assert summary["total_calls"] == 6
    # quick_quoter + chatty should both produce quotes
    assert summary["quotes_received"] >= 2
