"""
Portal tests — uses FastAPI TestClient against a temp SQLite db.
Covers: tier enforcement, masked vs unmasked data, admin routes, HTML view.
"""
from __future__ import annotations
import asyncio
import os
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    """
    Sync fixture: create + seed the SQLite DB before the portal starts.
    Returns (db_path, std_api_key, pro_api_key).
    asyncio.run() is safe here because pytest-asyncio hasn't started a loop
    for module scope.
    """
    db = str(tmp_path_factory.mktemp("portal") / "test.db")

    async def _setup():
        from ringaround.intel.store import IntelStore
        from ringaround.models import ProjectRequest, Job
        from ringaround.directory.mock import MockDirectoryProvider
        from ringaround.factory import build_call_flow
        from ringaround.jobs.runner import run_job

        store = IntelStore(db_path=db)
        await store.init()

        project = ProjectRequest(
            description="full bath remodel",
            zip_code="98101",
            category="bathroom_remodel",
        )
        directory = MockDirectoryProvider()
        contractors = await directory.find_contractors(project)
        job = Job(project=project, contractors=contractors)
        flow = build_call_flow()
        job = await run_job(job, flow)
        await store.record_job(job.id, project.zip_code, job.results)

        std_key = await store.create_subscription("std@test.com", tier="standard")
        pro_key = await store.create_subscription("pro@test.com", tier="pro")
        await store.close()
        return std_key, pro_key

    std_key, pro_key = asyncio.run(_setup())
    return db, std_key, pro_key


@pytest.fixture(scope="module")
def portal_client(seeded_db):
    """Start the FastAPI TestClient against the pre-seeded DB."""
    db, std_key, pro_key = seeded_db
    os.environ["INTEL_DB_PATH"] = db
    os.environ["ADMIN_API_KEY"] = "test-admin-key"

    from fastapi.testclient import TestClient
    # Import AFTER env var is set so lifespan reads it correctly
    from ringaround.web.app import app

    with TestClient(app) as client:
        yield client, std_key, pro_key


# ------------------------------------------------------------------ /api/v1/market

def test_market_free_tier_no_key(portal_client):
    client, _, _ = portal_client
    r = client.get("/api/v1/market/bathroom_remodel/98101")
    assert r.status_code == 200
    data = r.json()
    assert data["subscription_tier"] == "free"
    assert data["summary"]["days_back"] == 30


def test_market_standard_tier(portal_client):
    client, std_key, _ = portal_client
    r = client.get(
        "/api/v1/market/bathroom_remodel/98101",
        headers={"x-api-key": std_key},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["subscription_tier"] == "standard"
    assert data["summary"]["days_back"] == 90
    for comp in data["competitors"]:
        assert "Contractor" in comp["display_name"]


def test_market_pro_tier_unmasked(portal_client):
    client, _, pro_key = portal_client
    r = client.get(
        "/api/v1/market/bathroom_remodel/98101",
        headers={"x-api-key": pro_key},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["subscription_tier"] == "pro"
    names = [c["display_name"] for c in data["competitors"]]
    # Pro sees real business names, not "Contractor in..."
    assert any(
        not n.startswith("Contractor in") for n in names
    ), f"Expected unmasked names, got: {names}"


def test_market_invalid_key(portal_client):
    client, _, _ = portal_client
    r = client.get(
        "/api/v1/market/bathroom_remodel/98101",
        headers={"x-api-key": "bad-key-xyz"},
    )
    assert r.status_code == 401


# ------------------------------------------------------------------ /api/v1/price

def test_price_endpoint(portal_client):
    client, _, _ = portal_client
    r = client.get("/api/v1/price/bathroom_remodel/98101")
    assert r.status_code == 200
    data = r.json()
    assert "category" in data and "zip" in data and "data_points" in data


# ------------------------------------------------------------------ /api/v1/contractor

def test_contractor_history_requires_pro(portal_client):
    client, std_key, _ = portal_client
    r = client.get(
        "/api/v1/contractor/+12065550101",
        headers={"x-api-key": std_key},
    )
    assert r.status_code == 403


def test_contractor_history_pro(portal_client):
    client, _, pro_key = portal_client
    r = client.get(
        "/api/v1/contractor/+12065550101",
        headers={"x-api-key": pro_key},
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ------------------------------------------------------------------ /api/v1/me

def test_me_free(portal_client):
    client, _, _ = portal_client
    r = client.get("/api/v1/me")
    assert r.status_code == 200
    assert r.json()["tier"] == "free"


def test_me_standard(portal_client):
    client, std_key, _ = portal_client
    r = client.get("/api/v1/me", headers={"x-api-key": std_key})
    assert r.status_code == 200
    assert r.json()["tier"] == "standard"


# ------------------------------------------------------------------ admin

def test_admin_create_subscription(portal_client):
    client, _, _ = portal_client
    r = client.post(
        "/api/v1/admin/subscriptions",
        json={"email": "new@test.com", "tier": "standard"},
        headers={"x-admin-key": "test-admin-key"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "api_key" in data and len(data["api_key"]) > 10


def test_admin_requires_key(portal_client):
    client, _, _ = portal_client
    r = client.post(
        "/api/v1/admin/subscriptions",
        json={"email": "x@test.com", "tier": "free"},
    )
    assert r.status_code == 403


def test_admin_list(portal_client):
    client, _, _ = portal_client
    r = client.get(
        "/api/v1/admin/subscriptions",
        headers={"x-admin-key": "test-admin-key"},
    )
    assert r.status_code == 200
    subs = r.json()
    assert len(subs) >= 2
    for s in subs:
        assert s["api_key"].endswith("...")


# ------------------------------------------------------------------ HTML views

def test_portal_html_returns_200(portal_client):
    client, _, _ = portal_client
    r = client.get("/portal/bathroom_remodel/98101")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "bathroom" in r.text.lower()
    assert "FREE" in r.text


def test_portal_html_with_pro_key(portal_client):
    client, _, pro_key = portal_client
    r = client.get(f"/portal/bathroom_remodel/98101?key={pro_key}")
    assert r.status_code == 200
    assert "PRO" in r.text


def test_home_returns_html(portal_client):
    client, _, _ = portal_client
    r = client.get("/")
    assert r.status_code == 200
    assert "RingAround" in r.text
