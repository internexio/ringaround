"""
Live Google Places integration tests.
Skipped entirely when GOOGLE_PLACES_API_KEY is not set.

Run manually:
  GOOGLE_PLACES_API_KEY=... uv run pytest tests/test_google_places_live.py -v -s
"""
from __future__ import annotations
import os
import re
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("GOOGLE_PLACES_API_KEY"),
    reason="GOOGLE_PLACES_API_KEY not set",
)

from ringaround.models import ProjectRequest
from ringaround.directory.google_places import GooglePlacesProvider, _normalize_phone


_PROJECT = ProjectRequest(
    description="full bathroom remodel",
    zip_code="98101",
    category="bathroom_remodel",
)

_E164 = re.compile(r"^\+1\d{10}$")


async def test_places_returns_results():
    provider = GooglePlacesProvider()
    contractors = await provider.find_contractors(_PROJECT, limit=5)
    assert len(contractors) >= 1, "Expected at least 1 result for Seattle bathroom remodel"


async def test_places_phones_are_e164():
    provider = GooglePlacesProvider()
    contractors = await provider.find_contractors(_PROJECT, limit=10)
    for c in contractors:
        assert _E164.match(c.phone), f"Bad phone: {c.phone} for {c.name}"


async def test_places_category_populated():
    provider = GooglePlacesProvider()
    contractors = await provider.find_contractors(_PROJECT, limit=5)
    for c in contractors:
        assert c.category == "bathroom_remodel"
        assert c.source == "google_places"


async def test_places_no_duplicate_phones():
    provider = GooglePlacesProvider()
    contractors = await provider.find_contractors(_PROJECT, limit=20)
    phones = [c.phone for c in contractors]
    assert len(phones) == len(set(phones)), "Duplicate phone numbers in results"


async def test_places_limit_respected():
    provider = GooglePlacesProvider()
    contractors = await provider.find_contractors(_PROJECT, limit=3)
    assert len(contractors) <= 3


async def test_places_roofing_different_results():
    """Different category → different contractors."""
    roofing = ProjectRequest(
        description="full roof replacement",
        zip_code="98101",
        category="roofing",
    )
    provider = GooglePlacesProvider()
    bath = await provider.find_contractors(_PROJECT, limit=5)
    roof = await provider.find_contractors(roofing, limit=5)
    bath_phones = {c.phone for c in bath}
    roof_phones = {c.phone for c in roof}
    # Expect minimal overlap between bathroom remodelers and roofers
    overlap = bath_phones & roof_phones
    assert len(overlap) < min(len(bath_phones), len(roof_phones)), \
        "Too much overlap between bathroom and roofing results"


async def test_places_print_results(capsys):
    """Pretty-print results for manual inspection."""
    provider = GooglePlacesProvider()
    contractors = await provider.find_contractors(_PROJECT, limit=10)
    print(f"\nBathroom remodel contractors in 98101 ({len(contractors)} found):")
    for c in contractors:
        print(f"  {c.name:<40} {c.phone}  zip={c.zip_code}")
    assert len(contractors) > 0
