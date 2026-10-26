"""
RingAround Contractor Intel Portal — FastAPI app.

JSON API  →  /api/v1/*
HTML view →  /portal/{category}/{zip}

Tiers:
  free      — market summary only, masked competitors, 30-day window
  standard  — summary + masked competitor list, 90-day window
  pro       — unmasked names + phones, contractor history, full window

Start:
  uv pip install 'ringaround[web]'
  INTEL_DB_PATH=intel.db uvicorn ringaround.web.app:app --reload
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Path, Query
from fastapi.responses import HTMLResponse, JSONResponse
from ringaround.intel.store import IntelStore
from ringaround.intel.api import get_market_report, get_price_range, get_competitor_availability
from ringaround.intel.models import Subscription
from ringaround.web.auth import get_subscription, require_admin


# ------------------------------------------------------------------ app setup

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.getenv("INTEL_DB_PATH", "intel.db")
    store = IntelStore(db_path=db_path)
    await store.init()
    app.state.store = store
    yield
    await store.close()


app = FastAPI(
    title="RingAround Intel Portal",
    description="Contractor market intelligence — pricing, availability, competitor data.",
    version="0.1.0",
    lifespan=lifespan,
)


# ------------------------------------------------------------------ JSON API

@app.get("/api/v1/market/{category}/{zip_code}")
async def api_market(
    category: str = Path(..., examples=["bathroom_remodel"]),
    zip_code: str = Path(..., examples=["98101"]),
    days: int = Query(default=90, ge=7, le=365),
    sub: Subscription = Depends(get_subscription),
):
    """Market intelligence report for a category + zip."""
    effective_days = min(days, 30) if sub.tier == "free" else days
    report = await get_market_report(
        app.state.store, category, zip_code,
        days=effective_days, tier=sub.tier,
    )
    return report


@app.get("/api/v1/price/{category}/{zip_code}")
async def api_price(
    category: str = Path(..., examples=["bathroom_remodel"]),
    zip_code: str = Path(..., examples=["98101"]),
    sub: Subscription = Depends(get_subscription),
):
    """Quick price range — suitable for embedding in widgets or email digests."""
    days = 30 if sub.tier == "free" else 90
    return await get_price_range(app.state.store, category, zip_code, days=days)


@app.get("/api/v1/competitors/{category}/{zip_code}")
async def api_competitors(
    category: str = Path(..., examples=["bathroom_remodel"]),
    zip_code: str = Path(..., examples=["98101"]),
    days: int = Query(default=30, ge=7, le=90),
    sub: Subscription = Depends(get_subscription),
):
    """Contractors currently available for work in this market."""
    return await get_competitor_availability(app.state.store, category, zip_code, days=days)


@app.get("/api/v1/contractor/{phone}")
async def api_contractor(
    phone: str = Path(..., examples=["+12065550101"]),
    category: str | None = Query(default=None),
    sub: Subscription = Depends(get_subscription),
):
    """Pricing history for a specific contractor. Pro tier only."""
    if sub.tier not in ("pro",):
        raise HTTPException(
            status_code=403,
            detail="Contractor history requires a Pro subscription.",
        )
    history = await app.state.store.contractor_history(
        phone=phone, category=category, days=365
    )
    return history


@app.get("/api/v1/activity/{zip_code}")
async def api_activity(
    zip_code: str = Path(..., examples=["98101"]),
    days: int = Query(default=90, ge=7, le=365),
    sub: Subscription = Depends(get_subscription),
):
    """Observation counts by category in a zip — shows market depth."""
    return await app.state.store.zip_activity(zip_code, days=days)


@app.get("/api/v1/me")
async def api_me(sub: Subscription = Depends(get_subscription)):
    """Your subscription details."""
    return {
        "email": sub.email,
        "tier": sub.tier,
        "created_at": sub.created_at.isoformat(),
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
    }


# ------------------------------------------------------------------ admin

@app.post("/api/v1/admin/subscriptions", dependencies=[Depends(require_admin)])
async def admin_create_subscription(body: dict):
    """Create a new subscription. Body: {email, tier}"""
    email = body.get("email", "")
    tier = body.get("tier", "standard")
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    if tier not in ("free", "standard", "pro"):
        raise HTTPException(status_code=400, detail="tier must be free | standard | pro")
    api_key = await app.state.store.create_subscription(email=email, tier=tier)
    return {"api_key": api_key, "email": email, "tier": tier}


@app.get("/api/v1/admin/subscriptions", dependencies=[Depends(require_admin)])
async def admin_list_subscriptions():
    subs = await app.state.store.list_subscriptions()
    return [
        {
            "api_key": s.api_key[:8] + "...",  # partial key only
            "email": s.email,
            "tier": s.tier,
            "created_at": s.created_at.isoformat(),
        }
        for s in subs
    ]


# ------------------------------------------------------------------ HTML portal

@app.get("/portal/{category}/{zip_code}", response_class=HTMLResponse)
async def portal_view(
    category: str,
    zip_code: str,
    days: int = Query(default=90),
    x_api_key: str = Query(default="", alias="key"),
):
    """Human-readable market intelligence dashboard."""
    # resolve tier from ?key= query param (convenient for browser)
    if x_api_key:
        sub = await app.state.store.get_subscription(x_api_key)
        tier = sub.tier if sub else "free"
    else:
        tier = "free"
        sub = None

    effective_days = min(days, 30) if tier == "free" else days
    report = await get_market_report(
        app.state.store, category, zip_code,
        days=effective_days, tier=tier,
    )
    s = report.summary
    return HTMLResponse(_render_portal(category, zip_code, tier, s, report.competitors))


@app.get("/", response_class=HTMLResponse)
async def portal_home():
    total = await app.state.store.observation_count()
    return HTMLResponse(_render_home(total))


# ------------------------------------------------------------------ HTML rendering

_TIER_BADGE = {
    "free":     '<span style="background:#e5e7eb;padding:2px 8px;border-radius:12px;font-size:.75rem">FREE</span>',
    "standard": '<span style="background:#dbeafe;color:#1e40af;padding:2px 8px;border-radius:12px;font-size:.75rem">STANDARD</span>',
    "pro":      '<span style="background:#d1fae5;color:#065f46;padding:2px 8px;border-radius:12px;font-size:.75rem">PRO</span>',
}

_CSS = """
body{font-family:system-ui,-apple-system,sans-serif;max-width:960px;margin:40px auto;padding:0 24px;color:#111}
h1{font-size:1.4rem;margin-bottom:4px}
.sub{color:#6b7280;font-size:.9rem;margin-bottom:24px}
.metrics{display:flex;gap:32px;margin:20px 0;flex-wrap:wrap}
.metric .v{font-size:1.8rem;font-weight:700;color:#111}
.metric .l{font-size:.75rem;color:#6b7280;margin-top:2px}
table{width:100%;border-collapse:collapse;margin-top:16px;font-size:.9rem}
th{text-align:left;padding:8px 12px;border-bottom:2px solid #e5e7eb;color:#6b7280;font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}
td{padding:8px 12px;border-bottom:1px solid #f3f4f6}
tr:last-child td{border:none}
.avail-yes{color:#059669}
.avail-no{color:#dc2626}
.avail-unk{color:#6b7280}
.upsell{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 16px;margin-top:20px;font-size:.85rem;color:#92400e}
.nav{font-size:.85rem;margin-bottom:16px}
.nav a{color:#3b82f6;text-decoration:none}
"""


def _fmt(v: int | None) -> str:
    return f"${v:,}" if v is not None else "—"


def _avail_span(a: str) -> str:
    cls = {"available": "avail-yes", "unavailable": "avail-no"}.get(a, "avail-unk")
    icon = {"available": "✓", "unavailable": "✗"}.get(a, "?")
    return f'<span class="{cls}">{icon} {a}</span>'


def _render_portal(category, zip_code, tier, s, competitors) -> str:
    cat_display = category.replace("_", " ").title()
    badge = _TIER_BADGE.get(tier, "")

    # metrics row
    metrics_html = "\n".join([
        f'<div class="metric"><div class="v">{_fmt(s.price_low_median)}</div><div class="l">Median low price</div></div>',
        f'<div class="metric"><div class="v">{_fmt(s.price_low_p25)} – {_fmt(s.price_low_p75)}</div><div class="l">Low price range (p25–p75)</div></div>',
        f'<div class="metric"><div class="v">{s.observation_count}</div><div class="l">Observations ({s.days_back} days)</div></div>',
        f'<div class="metric"><div class="v">{s.contractor_count}</div><div class="l">Unique contractors</div></div>',
        f'<div class="metric"><div class="v">{s.availability_rate:.0%}</div><div class="l">Currently available</div></div>',
    ] + ([f'<div class="metric"><div class="v">{s.avg_timeline_weeks}w</div><div class="l">Avg weeks to start</div></div>'] if s.avg_timeline_weeks else []))

    # competitors table
    if competitors:
        rows_html = "\n".join(
            f"<tr>"
            f"<td>{c.display_name}</td>"
            f"<td>{_fmt(c.price_low)}</td>"
            f"<td>{_fmt(c.price_high)}</td>"
            f"<td>{_avail_span(c.availability)}</td>"
            f"<td>{f'{c.timeline_weeks}w' if c.timeline_weeks else '—'}</td>"
            f"<td>{c.observed_at.strftime('%Y-%m-%d')}</td>"
            f"</tr>"
            for c in competitors
        )
        table_html = f"""
        <h2 style="margin-top:32px;font-size:1rem;color:#374151">Competitor pricing</h2>
        <table>
          <tr><th>Contractor</th><th>Low</th><th>High</th><th>Availability</th><th>Starts</th><th>Observed</th></tr>
          {rows_html}
        </table>"""
    else:
        table_html = '<p style="color:#6b7280;margin-top:16px">No observations yet for this market. Run <code>ringaround run</code> to collect data.</p>'

    upsell = ""
    if tier == "free":
        upsell = '<div class="upsell">⬆ <strong>Upgrade to Standard</strong> to see 90 days of data and the full competitor list.</div>'
    elif tier == "standard":
        upsell = '<div class="upsell">⬆ <strong>Upgrade to Pro</strong> to see contractor names, phone numbers, and individual pricing history.</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>RingAround — {cat_display} {zip_code}</title>
<style>{_CSS}</style></head>
<body>
<div class="nav"><a href="/">← RingAround Intel</a></div>
<h1>{cat_display} · {zip_code} &nbsp;{badge}</h1>
<div class="sub">Market intelligence · last {s.days_back} days · {s.observation_count} observations</div>
<div class="metrics">{metrics_html}</div>
{table_html}
{upsell}
</body></html>"""


def _render_home(total_obs: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>RingAround Intel Portal</title>
<style>{_CSS}</style></head>
<body>
<h1>RingAround Intel Portal</h1>
<p class="sub">Market pricing intelligence for home service contractors.</p>
<div class="metrics">
  <div class="metric"><div class="v">{total_obs:,}</div><div class="l">Quote observations</div></div>
</div>

<h2 style="font-size:1rem;margin-top:32px">Try a market</h2>
<ul>
  <li><a href="/portal/bathroom_remodel/98101">Bathroom Remodel · Seattle 98101</a></li>
  <li><a href="/portal/roofing/98101">Roofing · Seattle 98101</a></li>
  <li><a href="/portal/hvac/98101">HVAC · Seattle 98101</a></li>
</ul>

<h2 style="font-size:1rem;margin-top:32px">JSON API</h2>
<ul style="font-size:.9rem">
  <li><code>GET /api/v1/market/{{category}}/{{zip}}</code> — market report</li>
  <li><code>GET /api/v1/price/{{category}}/{{zip}}</code> — price widget</li>
  <li><code>GET /api/v1/competitors/{{category}}/{{zip}}</code> — available contractors</li>
  <li><code>GET /api/v1/contractor/{{phone}}</code> — contractor history (Pro)</li>
  <li><code>GET /api/v1/me</code> — subscription info</li>
</ul>
<p style="font-size:.85rem;color:#6b7280">Pass your API key as <code>X-Api-Key: ...</code> header or <code>?key=...</code> query param.</p>

<p style="margin-top:40px;font-size:.8rem;color:#9ca3af">
  <a href="/docs">OpenAPI docs</a> · RingAround 0.1.0
</p>
</body></html>"""
