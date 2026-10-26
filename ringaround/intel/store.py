"""
Intel store — async SQLite wrapper (stdlib sqlite3 + asyncio.to_thread).
No extra dependencies. One IntelStore instance per process; call init()
before first use.

WAL mode lets reads and writes run concurrently. Writes are serialised
through an asyncio.Lock so concurrent call completions don't corrupt rows.
"""
from __future__ import annotations
import asyncio
import sqlite3
import statistics
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from ringaround.models import CallResult, CallState
from ringaround.intel.models import QuoteObservation, MarketSummary

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS quote_observations (
    id                TEXT PRIMARY KEY,
    job_id            TEXT NOT NULL,
    call_id           TEXT NOT NULL,

    contractor_name   TEXT NOT NULL,
    contractor_phone  TEXT NOT NULL,
    contractor_zip    TEXT NOT NULL,
    place_id          TEXT,

    category          TEXT NOT NULL,
    project_zip       TEXT NOT NULL,

    price_low         INTEGER,
    price_high        INTEGER,
    availability      TEXT NOT NULL DEFAULT 'unknown',
    timeline_weeks    INTEGER,
    confidence        REAL NOT NULL DEFAULT 0.0,
    raw_quote_text    TEXT NOT NULL DEFAULT '',

    observed_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cat_zip
    ON quote_observations(category, project_zip);
CREATE INDEX IF NOT EXISTS idx_observed_at
    ON quote_observations(observed_at);
CREATE INDEX IF NOT EXISTS idx_contractor_phone
    ON quote_observations(contractor_phone);
"""

_INSERT = """
INSERT OR IGNORE INTO quote_observations (
    id, job_id, call_id,
    contractor_name, contractor_phone, contractor_zip, place_id,
    category, project_zip,
    price_low, price_high, availability, timeline_weeks,
    confidence, raw_quote_text, observed_at
) VALUES (
    :id, :job_id, :call_id,
    :contractor_name, :contractor_phone, :contractor_zip, :place_id,
    :category, :project_zip,
    :price_low, :price_high, :availability, :timeline_weeks,
    :confidence, :raw_quote_text, :observed_at
)
"""


def _percentile(data: list[float | int], pct: float) -> int:
    """Nearest-rank percentile. Returns int (prices are whole dollars)."""
    if not data:
        return 0
    sorted_d = sorted(data)
    idx = max(0, int(len(sorted_d) * pct / 100) - 1)
    return int(sorted_d[idx])


def _row_to_obs(row: sqlite3.Row) -> QuoteObservation:
    return QuoteObservation(
        id=row["id"],
        job_id=row["job_id"],
        call_id=row["call_id"],
        contractor_name=row["contractor_name"],
        contractor_phone=row["contractor_phone"],
        contractor_zip=row["contractor_zip"],
        place_id=row["place_id"],
        category=row["category"],
        project_zip=row["project_zip"],
        price_low=row["price_low"],
        price_high=row["price_high"],
        availability=row["availability"],
        timeline_weeks=row["timeline_weeks"],
        confidence=row["confidence"],
        raw_quote_text=row["raw_quote_text"] or "",
        observed_at=datetime.fromisoformat(row["observed_at"]),
    )


class IntelStore:
    def __init__(self, db_path: str | Path = "intel.db"):
        self._path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._write_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------ setup

    def _write_lock_safe(self) -> asyncio.Lock:
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        return self._write_lock

    def _init_sync(self) -> None:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.commit()
        self._conn = conn

    async def init(self) -> None:
        """Create schema. Call once at startup."""
        await asyncio.to_thread(self._init_sync)

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("IntelStore.init() was not awaited before use")
        return self._conn

    async def close(self) -> None:
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    # ------------------------------------------------------------------ write

    async def record_quote(self, result: CallResult) -> None:
        """Persist a completed call's quote. No-op if no quote was extracted."""
        if not result.got_quote or result.quote is None:
            return

        q = result.quote
        row = {
            "id": str(uuid.uuid4()),
            "job_id": result.job_id,
            "call_id": result.id,
            "contractor_name": result.contractor.name,
            "contractor_phone": result.contractor.phone,
            "contractor_zip": result.contractor.zip_code,
            "place_id": result.contractor.place_id,
            "category": result.contractor.category,
            "project_zip": result.job_id,  # project zip lives on Job; best-effort from job_id
            "price_low": q.price_low,
            "price_high": q.price_high,
            "availability": q.availability,
            "timeline_weeks": q.timeline_weeks,
            "confidence": q.confidence,
            "raw_quote_text": q.raw_quote_text,
            "observed_at": datetime.utcnow().isoformat(),
        }

        conn = self._require_conn()
        async with self._write_lock_safe():
            await asyncio.to_thread(self._insert_sync, conn, row)

    async def record_job(self, job_id: str, project_zip: str, results: list[CallResult]) -> int:
        """Record all quote-bearing results from a completed job. Returns count written."""
        written = 0
        for result in results:
            if not result.got_quote or result.quote is None:
                continue
            q = result.quote
            row = {
                "id": str(uuid.uuid4()),
                "job_id": job_id,
                "call_id": result.id,
                "contractor_name": result.contractor.name,
                "contractor_phone": result.contractor.phone,
                "contractor_zip": result.contractor.zip_code,
                "place_id": result.contractor.place_id,
                "category": result.contractor.category,
                "project_zip": project_zip,
                "price_low": q.price_low,
                "price_high": q.price_high,
                "availability": q.availability,
                "timeline_weeks": q.timeline_weeks,
                "confidence": q.confidence,
                "raw_quote_text": q.raw_quote_text,
                "observed_at": datetime.utcnow().isoformat(),
            }
            conn = self._require_conn()
            async with self._write_lock_safe():
                await asyncio.to_thread(self._insert_sync, conn, row)
            written += 1
        return written

    @staticmethod
    def _insert_sync(conn: sqlite3.Connection, row: dict) -> None:
        conn.execute(_INSERT, row)
        conn.commit()

    # ------------------------------------------------------------------ read

    async def market_summary(
        self,
        category: str,
        project_zip: str,
        days: int = 90,
    ) -> MarketSummary:
        """Aggregate price/availability stats for a category + zip over the last N days."""
        observations = await self.recent_observations(category, project_zip, days=days)
        return _build_summary(category, project_zip, days, observations)

    async def recent_observations(
        self,
        category: str,
        project_zip: str,
        days: int = 90,
        limit: int = 200,
    ) -> list[QuoteObservation]:
        """Raw quote records for a category + zip — used by the contractor portal."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        sql = """
            SELECT * FROM quote_observations
            WHERE category = ?
              AND project_zip = ?
              AND observed_at >= ?
            ORDER BY observed_at DESC
            LIMIT ?
        """
        conn = self._require_conn()
        rows = await asyncio.to_thread(
            lambda: conn.execute(sql, (category, project_zip, cutoff, limit)).fetchall()
        )
        return [_row_to_obs(r) for r in rows]

    async def contractor_history(
        self,
        phone: str,
        category: str | None = None,
        days: int = 365,
    ) -> list[QuoteObservation]:
        """All quotes from a specific contractor — useful for pricing trend analysis."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        if category:
            sql = """
                SELECT * FROM quote_observations
                WHERE contractor_phone = ?
                  AND category = ?
                  AND observed_at >= ?
                ORDER BY observed_at DESC
            """
            args = (phone, category, cutoff)
        else:
            sql = """
                SELECT * FROM quote_observations
                WHERE contractor_phone = ?
                  AND observed_at >= ?
                ORDER BY observed_at DESC
            """
            args = (phone, cutoff)
        conn = self._require_conn()
        rows = await asyncio.to_thread(
            lambda: conn.execute(sql, args).fetchall()
        )
        return [_row_to_obs(r) for r in rows]

    async def zip_activity(
        self,
        project_zip: str,
        days: int = 90,
    ) -> dict[str, int]:
        """Observation count per category in a zip — helps subscribers see market depth."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        sql = """
            SELECT category, COUNT(*) as cnt
            FROM quote_observations
            WHERE project_zip = ?
              AND observed_at >= ?
            GROUP BY category
            ORDER BY cnt DESC
        """
        conn = self._require_conn()
        rows = await asyncio.to_thread(
            lambda: conn.execute(sql, (project_zip, cutoff)).fetchall()
        )
        return {r["category"]: r["cnt"] for r in rows}

    async def observation_count(self) -> int:
        """Total rows in the store."""
        conn = self._require_conn()
        row = await asyncio.to_thread(
            lambda: conn.execute("SELECT COUNT(*) FROM quote_observations").fetchone()
        )
        return row[0]


# ------------------------------------------------------------------ helpers

def _build_summary(
    category: str,
    project_zip: str,
    days: int,
    observations: list[QuoteObservation],
) -> MarketSummary:
    prices_low = [o.price_low for o in observations if o.price_low is not None]
    prices_high = [o.price_high for o in observations if o.price_high is not None]
    available = [o for o in observations if o.availability == "available"]
    timelines = [o.timeline_weeks for o in observations if o.timeline_weeks is not None]
    phones = {o.contractor_phone for o in observations}

    def _med(lst: list) -> int | None:
        return int(statistics.median(lst)) if len(lst) >= 3 else None

    return MarketSummary(
        category=category,
        project_zip=project_zip,
        days_back=days,
        observation_count=len(observations),
        contractor_count=len(phones),
        price_low_p25=_percentile(prices_low, 25) if len(prices_low) >= 3 else None,
        price_low_median=_med(prices_low),
        price_low_p75=_percentile(prices_low, 75) if len(prices_low) >= 3 else None,
        price_high_median=_med(prices_high),
        availability_rate=len(available) / len(observations) if observations else 0.0,
        avg_timeline_weeks=round(statistics.mean(timelines), 1) if timelines else None,
        generated_at=datetime.utcnow(),
    )
