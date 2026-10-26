"""
API key → subscription resolution.

Rules:
  No key          → free tier (read-only, masked, 30-day window)
  Valid key       → tier from subscriptions table
  Invalid/expired → 401

Admin endpoints check X-Admin-Key against ADMIN_API_KEY env var.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from fastapi import Header, HTTPException, Request
from ringaround.intel.models import Subscription

_FREE_TIER = Subscription(
    api_key="",
    email="anonymous",
    tier="free",
    created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    expires_at=None,
)


async def get_subscription(
    request: Request,
    x_api_key: str = Header(default=""),
) -> Subscription:
    """FastAPI dependency — resolves caller tier from X-Api-Key header."""
    if not x_api_key:
        return _FREE_TIER

    store = request.app.state.store
    sub = await store.get_subscription(x_api_key)
    if sub is None:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    return sub


async def require_admin(x_admin_key: str = Header(default="")) -> None:
    """FastAPI dependency — guards admin-only endpoints."""
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Admin key required")
