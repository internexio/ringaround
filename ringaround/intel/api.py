"""
Intel query API — report objects for the contractor subscription portal.

Subscribing contractors ask questions like:
  "What are bathroom remodelers charging in 98101 right now?"
  "Which competitors in my area are available to take work?"
  "How has pricing trended over the last 90 days?"

This layer composes IntelStore queries into display-ready reports.
It does NOT do auth — access control belongs in the web layer.
"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel
from ringaround.intel.store import IntelStore
from ringaround.intel.models import QuoteObservation, MarketSummary


class CompetitorEntry(BaseModel):
    """One competitor as seen from the portal — name and phone are masked for
    non-paying tiers; set mask=False for full subscribers."""
    display_name: str            # "Contractor #3" or real name for paid tier
    zip_code: str
    price_low: int | None
    price_high: int | None
    availability: str
    timeline_weeks: int | None
    observed_at: datetime

    @classmethod
    def from_observation(cls, obs: QuoteObservation, mask: bool = True) -> "CompetitorEntry":
        name = f"Contractor in {obs.contractor_zip}" if mask else obs.contractor_name
        return cls(
            display_name=name,
            zip_code=obs.contractor_zip,
            price_low=obs.price_low,
            price_high=obs.price_high,
            availability=obs.availability,
            timeline_weeks=obs.timeline_weeks,
            observed_at=obs.observed_at,
        )


class IntelReport(BaseModel):
    """Full intel package for the portal: summary + individual competitor entries."""
    summary: MarketSummary
    competitors: list[CompetitorEntry]
    subscription_tier: str       # "free" | "standard" | "pro"


async def get_market_report(
    store: IntelStore,
    category: str,
    project_zip: str,
    days: int = 90,
    tier: str = "standard",
) -> IntelReport:
    """
    Build the intel report a subscriber sees.

    Tiers:
      free     — summary stats only, all competitors masked, last 30 days
      standard — summary + masked competitor list, last 90 days
      pro      — summary + unmasked competitor names + phones, full history
    """
    if tier == "free":
        days = min(days, 30)

    summary = await store.market_summary(category, project_zip, days=days)
    observations = await store.recent_observations(
        category, project_zip, days=days, limit=50
    )

    mask = tier != "pro"
    competitors = [
        CompetitorEntry.from_observation(obs, mask=mask)
        for obs in observations
    ]

    return IntelReport(
        summary=summary,
        competitors=competitors,
        subscription_tier=tier,
    )


async def get_competitor_availability(
    store: IntelStore,
    category: str,
    project_zip: str,
    days: int = 30,
) -> list[CompetitorEntry]:
    """Quick availability snapshot — who's open for work right now in this zip."""
    observations = await store.recent_observations(category, project_zip, days=days)
    available = [o for o in observations if o.availability == "available"]
    return [CompetitorEntry.from_observation(o, mask=True) for o in available]


async def get_price_range(
    store: IntelStore,
    category: str,
    project_zip: str,
    days: int = 90,
) -> dict:
    """Quick price range for embedding in a homepage widget or email digest."""
    summary = await store.market_summary(category, project_zip, days=days)
    return {
        "category": category,
        "zip": project_zip,
        "market_low": summary.price_low_p25,
        "market_mid": summary.price_low_median,
        "market_high": summary.price_low_p75,
        "data_points": summary.observation_count,
        "as_of": summary.generated_at.isoformat(),
    }
