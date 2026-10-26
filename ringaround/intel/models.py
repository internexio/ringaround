"""
Intel store Pydantic models — separate from ringaround.models to keep the
call-pipeline layer independent of the analytics layer.
"""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class QuoteObservation(BaseModel):
    """One recorded quote from a completed call. Immutable once written."""
    id: str
    job_id: str
    call_id: str

    # contractor
    contractor_name: str
    contractor_phone: str
    contractor_zip: str
    place_id: str | None

    # project context
    category: str
    project_zip: str

    # quote payload
    price_low: int | None
    price_high: int | None
    availability: str                  # available | unavailable | unknown
    timeline_weeks: int | None
    confidence: float
    raw_quote_text: str

    observed_at: datetime


class Subscription(BaseModel):
    api_key: str
    email: str
    tier: str                      # free | standard | pro
    created_at: datetime
    expires_at: datetime | None


class MarketSummary(BaseModel):
    """Aggregated market intelligence for a category + zip slice."""
    category: str
    project_zip: str
    days_back: int
    observation_count: int
    contractor_count: int              # unique contractors seen

    # price distribution (None when < 3 data points)
    price_low_p25: int | None
    price_low_median: int | None
    price_low_p75: int | None
    price_high_median: int | None

    availability_rate: float           # fraction of respondents who are available
    avg_timeline_weeks: float | None

    generated_at: datetime
