from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field
import uuid


class CallState(str, Enum):
    DIALING = "dialing"
    INTRO = "intro"
    CONFIRM_PROJECT = "confirm_project"
    QUOTE_ASK = "quote_ask"
    FOLLOW_UP = "follow_up"
    CLOSE = "close"
    # terminal
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    REFUSED = "refused"
    OUT_OF_AREA = "out_of_area"
    UNAVAILABLE = "unavailable"
    CALLBACK_SCHEDULED = "callback_scheduled"
    FAILED = "failed"


TERMINAL_STATES = {
    CallState.COMPLETED, CallState.NO_ANSWER, CallState.REFUSED,
    CallState.OUT_OF_AREA, CallState.UNAVAILABLE,
    CallState.CALLBACK_SCHEDULED, CallState.FAILED,
}


class TurnIntent(str, Enum):
    POSITIVE = "positive"
    GAVE_QUOTE = "gave_quote"
    NEEDS_MORE_INFO = "needs_more_info"
    UNAVAILABLE = "unavailable"
    CALL_BACK = "call_back"
    REFUSED = "refused"
    OUT_OF_AREA = "out_of_area"
    HUNG_UP = "hung_up"
    UNCLEAR = "unclear"


class Contractor(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    phone: str
    zip_code: str
    category: str
    source: str = "mock"
    place_id: str | None = None         # Google Places ID for intel dedup
    mock_persona: str = "quick_quoter"  # used only by mock providers


class ProjectRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    zip_code: str
    category: str              # "bathroom_remodel", "roofing", "hvac", etc.
    budget_hint: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Turn(BaseModel):
    state: CallState
    agent_text: str
    vendor_text: str | None = None
    intent: TurnIntent | None = None


class Quote(BaseModel):
    price_low: int | None = None       # USD
    price_high: int | None = None      # USD
    availability: Literal["available", "unavailable", "unknown"] = "unknown"
    timeline_weeks: int | None = None
    license_mentioned: bool = False
    callback_requested: bool = False
    confidence: float = 0.0            # 0-1
    raw_quote_text: str = ""


class CallResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    contractor: Contractor
    final_state: CallState
    turns: list[Turn] = Field(default_factory=list)
    quote: Quote | None = None
    duration_seconds: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None

    @property
    def got_quote(self) -> bool:
        return (
            self.final_state == CallState.COMPLETED
            and self.quote is not None
            and self.quote.price_low is not None
        )


class Job(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project: ProjectRequest
    contractors: list[Contractor] = Field(default_factory=list)
    results: list[CallResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @property
    def quotes(self) -> list[CallResult]:
        return [r for r in self.results if r.got_quote]

    @property
    def ranked_quotes(self) -> list[CallResult]:
        return sorted(self.quotes, key=lambda r: r.quote.price_low or 999_999)
