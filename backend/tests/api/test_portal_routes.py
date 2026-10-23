"""Owner Portal + Review Console routes against Postgres (a throwaway schema; skipped without
Postgres): roles, submit, review decisions, and approval putting a service in the catalog."""
import json
import os
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi import FastAPI

from backend.app.db import portal, registry
from backend.app.db.registry.repository import DEFAULT_DATABASE_URL
from backend.app.mapper import map_service
from backend.app.spec import parse_spec
from backend.tests.dev3_support import bearer, login

ROOT = Path(__file__).resolve().parents[3]
PINE = json.loads((ROOT / "backend/app/db/registry/manifests/pine_and_petal_1.0.json").read_text(encoding="utf-8"))
QUICKFIX = json.loads((ROOT / "backend/app/db/registry/manifests/quickfix_1.0.json").read_text(encoding="utf-8"))
SCHEMA = "portal_test"


@pytest.fixture
def pg(monkeypatch, dev3_env):
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable")
    conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.execute(f"CREATE SCHEMA {SCHEMA}")
    monkeypatch.setenv("DATABASE_URL", f"{url}?options=-csearch_path%3D{SCHEMA}")
    monkeypatch.setenv("GENERATED_DIR", str(ROOT / ".pytest_cache" / "portal_generated"))
    registry.create_tables()
    portal.create_tables()
    spec = parse_spec(json.loads((ROOT / "mock-services/catalog/specs/demo_bistro.json").read_text(encoding="utf-8")))
    registry.upsert_service(spec)
    registry.upsert_endpoints(spec.service_uuid, map_service(spec))
    for user_id, role in [("alice", "user"), ("bistro-owner", "owner"), ("pine-owner", "owner"),
                          ("other-owner", "owner"), ("rev", "reviewer")]:
        portal.ensure_user(user_id, role=role)
    registry.ensure_business(spec.service_uuid, owner_user_id="bistro-owner")
    dev3_env(REGISTRY="postgres")
    yield
    conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
    conn.close()


@pytest.fixture
async def api(pg):
    from backend.app.api.portal import router as portal_router
    from backend.app.api.router import router as api_router
    from backend.app.auth.router import router as auth_router

    app = FastAPI()
    for r in (auth_router, api_router, portal_router):
        app.include_router(r)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client:
        yield client


async def as_user(api, name):
    return bearer(await login(api, name))


async def test_roles_are_enforced(api):
    alice = await as_user(api, "alice")
    owner = await as_user(api, "pine-owner")
    assert (await api.get("/api/review/submissions", headers=alice)).status_code == 403
    assert (await api.get("/api/review/submissions", headers=owner)).status_code == 403
    assert (await api.get("/api/owner/connectors", headers=alice)).status_code == 403
    assert (await api.get("/api/owner/connectors")).status_code == 401
    # A brand-new username signs in as a plain user.
    newbie = await as_user(api, "newbie")
    assert (await api.get("/me", headers=newbie)).json()["role"] == "user"


async def test_demo_users_lists_by_role(api):
    users = (await api.get("/auth/demo-users")).json()
    assert [u["user_id"] for u in users] == ["alice"]
    reviewers = (await api.get("/auth/demo-users?role=reviewer")).json()
    assert [u["user_id"] for u in reviewers] == ["rev"]


async def test_submit_review_approve_puts_the_service_in_the_catalog(api):
    owner, rev, alice = [await as_user(api, n) for n in ("pine-owner", "rev", "alice")]
    # Checks first (nothing stored), then the submission.
    report = (await api.post("/api/owner/checks", json={"manifest": PINE}, headers=owner)).json()
    assert report["passed"] and len(report["tools"]) == 2
    sub = await api.post("/api/owner/submissions", json={"manifest": PINE, "message": "hi"}, headers=owner)
    assert sub.status_code == 201
    sub_id = sub.json()["id"]
    # One open submission per domain; and only its owner may submit for it.
    assert (await api.post("/api/owner/submissions", json={"manifest": PINE}, headers=owner)).status_code == 409
    other = await as_user(api, "other-owner")
    assert (await api.post("/api/owner/submissions", json={"manifest": PINE}, headers=other)).status_code == 403
    # Not in the catalog yet.
    found = (await api.post("/resolve-service", json={"query": "pinepetal.test"}, headers=alice)).json()
    assert found["status"] == "not_found"

    queue = (await api.get("/api/review/submissions?status=pending", headers=rev)).json()
    assert [s["id"] for s in queue] == [sub_id]
    assert (await api.post(f"/api/review/submissions/{sub_id}/start", headers=rev)).json()["status"] == "in_review"
    short = await api.post(f"/api/review/submissions/{sub_id}/reject", json={"reason": "no"}, headers=rev)
    assert short.status_code == 422
    approved = await api.post(f"/api/review/submissions/{sub_id}/approve", json={"note": "ok"}, headers=rev)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert (await api.post(f"/api/review/submissions/{sub_id}/approve", json={}, headers=rev)).status_code == 409

    found = (await api.post("/resolve-service", json={"query": "pinepetal.test"}, headers=alice)).json()
    assert found["status"] == "resolved"
    uuid = found["service"]["service_uuid"]
    details = (await api.get(f"/services/{uuid}", headers=alice)).json()
    assert {t["name"] for t in details["tools"]} == {"search_bouquets", "order_bouquet"}
    assert details["profile"]["city"] == "Oak Park" and details["published"] is False
    assert "Pine & Petal" in [s["service_name"] for s in (await api.get("/services", headers=alice)).json()]

    connectors = (await api.get("/api/owner/connectors", headers=owner)).json()
    assert [(c["service_name"], c["status"], c["live_version"]) for c in connectors] == [
        ("Pine & Petal", "approved", "1.0")]
    notes = (await api.get("/me/notifications", headers=owner)).json()
    assert "approved" in notes[0]["text"]
    catalog = (await api.get("/api/review/catalog", headers=rev)).json()
    assert {c["service_name"]: c["approved_version"] for c in catalog}["Pine & Petal"] == "1.0"


async def test_failing_manifest_cant_be_submitted(api):
    owner = await as_user(api, "pine-owner")
    resp = await api.post("/api/owner/submissions", json={"manifest": QUICKFIX}, headers=owner)
    assert resp.status_code == 422 and "Fix the failed checks" in resp.json()["detail"]


async def test_another_owners_domain_is_refused(api):
    bistro = json.loads(json.dumps(PINE))
    bistro["publisher"]["domain"] = "demobistro.test"
    resp = await api.post("/api/owner/submissions", json={"manifest": bistro}, headers=await as_user(api, "pine-owner"))
    assert resp.status_code == 403


async def test_reject_notifies_the_owner(api):
    owner, rev = [await as_user(api, n) for n in ("pine-owner", "rev")]
    sub_id = (await api.post("/api/owner/submissions", json={"manifest": PINE}, headers=owner)).json()["id"]
    resp = await api.post(f"/api/review/submissions/{sub_id}/reject",
                          json={"reason": "Please add a refund policy link to the publisher block."}, headers=rev)
    assert resp.json()["status"] == "rejected"
    assert "rejected" in (await api.get("/me/notifications", headers=owner)).json()[0]["text"]
    # Rejected -> the owner can send a fixed version again.
    fixed = json.loads(json.dumps(PINE))
    fixed["openapi"]["info"]["version"] = "1.0.1"
    assert (await api.post("/api/owner/submissions", json={"manifest": fixed}, headers=owner)).status_code == 201
