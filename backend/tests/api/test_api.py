"""REST API (C7): OAuth connect, publish jobs, /me/services. Runs in-process, no network."""
import asyncio

import httpx
import pytest

from backend.app.api import jobs
from backend.app.auth import factory
from backend.app.auth.services import OAuthInfo, ServiceInfo
from backend.app.pipeline.models import PublishResult, StepError
from backend.tests.dev3_support import DEMO_UUID, bearer, login, oauth_app

OTHER_UUID = "22222222-2222-2222-2222-222222222222"
MCP_URL = f"http://gw.test/mcp/{DEMO_UUID}"


async def token_for(api, name: str) -> dict:
    return bearer(await login(api, name))


async def finish(tracker: jobs.PublishJobs) -> None:
    await asyncio.gather(*tracker._tasks)


# ---- every protected route answers a bare 401 ----

@pytest.mark.parametrize("method, path, body", [
    ("GET", f"/oauth/start?service_uuid={DEMO_UUID}", None),
    ("POST", "/publish", {"service_uuid": DEMO_UUID}),
    ("GET", "/publish/abc", None),
    ("GET", "/me/services", None),
])
async def test_protected_routes_need_a_token(api, method, path, body):
    for headers in ({}, {"Authorization": "Bearer nonsense"}):
        resp = await api.request(method, path, json=body, headers=headers)
        assert resp.status_code == 401
        assert "www-authenticate" not in resp.headers


# ---- OAuth ----

async def test_oauth_round_trip_connects_the_user(api):
    headers = await token_for(api, "alice")
    start = await api.get("/oauth/start", params={"service_uuid": DEMO_UUID}, headers=headers)
    assert start.status_code == 200
    auth_url = start.json()["auth_url"]
    assert auth_url.startswith("http://localhost:9100/authorize?") and "state=" in auth_url

    # The browser signs in on the service's page, which sends it to our callback.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=oauth_app),
                                 base_url="http://oauth.test") as page:
        redirect = await page.get("/" + auth_url.split("://", 1)[1].split("/", 1)[1])
    callback = httpx.URL(redirect.headers["location"])
    resp = await api.get("/oauth/callback", params=dict(callback.params))  # no user token needed
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://ui.test/connect/done?status=ok"

    assert factory.get_token_store().get("alice", DEMO_UUID) is not None
    assert factory.get_mapping().get_connection("alice", DEMO_UUID).status == "active"


async def test_oauth_start_unknown_service(api):
    headers = await token_for(api, "alice")
    resp = await api.get("/oauth/start", params={"service_uuid": OTHER_UUID}, headers=headers)
    assert resp.status_code == 404 and resp.json()["detail"] == "unknown service"


async def test_oauth_start_rejects_odd_service_ids(api):
    headers = await token_for(api, "alice")
    resp = await api.get("/oauth/start", params={"service_uuid": "../etc"}, headers=headers)
    assert resp.status_code == 422


@pytest.mark.parametrize("params", [
    {"code": "c", "state": "forged.state"},   # state not signed by us
    {"code": "", "state": ""},                # malformed
    {"error": "access_denied", "state": "s"},  # the user said no
    {},
])
async def test_oauth_callback_failures_redirect_with_error(api, params):
    resp = await api.get("/oauth/callback", params=params)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://ui.test/connect/done?status=error"
    assert factory.get_mapping().list_for_user("alice") == []


async def test_oauth_callback_survives_a_broken_token_store(api, monkeypatch):
    headers = await token_for(api, "alice")
    start = await api.get("/oauth/start", params={"service_uuid": DEMO_UUID}, headers=headers)
    auth_url = start.json()["auth_url"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=oauth_app),
                                 base_url="http://oauth.test") as page:
        redirect = await page.get("/" + auth_url.split("://", 1)[1].split("/", 1)[1])

    class Broken:
        def put(self, *args):
            raise RuntimeError("store down")

    monkeypatch.setattr(factory, "get_token_store", lambda: Broken())
    resp = await api.get("/oauth/callback", params=dict(httpx.URL(redirect.headers["location"]).params))
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("status=error")


# ---- publish jobs ----

def use_publish(fake) -> jobs.PublishJobs:
    tracker = jobs.PublishJobs(publish=fake)
    jobs.set_jobs(tracker)
    return tracker


async def test_publish_job_reports_each_stage_then_done(api):
    gate = asyncio.Event()

    async def fake(user_id, service_uuid, on_progress):
        on_progress("generating")
        await gate.wait()
        on_progress("deploying")
        return PublishResult(status="done", mcp_url=MCP_URL, version="1")

    tracker = use_publish(fake)
    headers = await token_for(api, "alice")
    started = await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=headers)
    job_id = started.json()["job_id"]
    await asyncio.sleep(0)  # let the background task reach the gate

    running = (await api.get(f"/publish/{job_id}", headers=headers)).json()
    assert (running["status"], running["stage"]) == ("running", "generating")
    assert running["mcp_url"] is None

    gate.set()
    await finish(tracker)
    done = (await api.get(f"/publish/{job_id}", headers=headers)).json()
    assert done == {"status": "done", "stage": "done", "mcp_url": MCP_URL, "skipped": False,
                    "version": "1", "error": None}


async def test_publish_job_passes_the_users_id_from_the_token(api):
    seen = []

    async def fake(user_id, service_uuid, on_progress):
        seen.append((user_id, service_uuid))
        return PublishResult(status="done", mcp_url=MCP_URL, skipped=True, version="1")

    tracker = use_publish(fake)
    headers = await token_for(api, "alice")
    resp = await api.post("/publish", json={"service_uuid": DEMO_UUID, "user_id": "mallory"}, headers=headers)
    await finish(tracker)
    assert seen == [("alice", DEMO_UUID)]  # a user_id in the body is ignored
    status = (await api.get(f"/publish/{resp.json()['job_id']}", headers=headers)).json()
    assert status["skipped"] is True


async def test_publish_failure_is_reported_with_its_step(api):
    async def fake(user_id, service_uuid, on_progress):
        on_progress("failed")
        return PublishResult(status="failed",
                             error=StepError(step="connect", code="NOT_CONNECTED", message="Connect first."))

    tracker = use_publish(fake)
    headers = await token_for(api, "alice")
    job_id = (await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=headers)).json()["job_id"]
    await finish(tracker)
    body = (await api.get(f"/publish/{job_id}", headers=headers)).json()
    assert body["status"] == "failed" and body["stage"] == "failed"
    assert body["error"] == {"step": "connect", "code": "NOT_CONNECTED", "message": "Connect first."}


async def test_crashing_publish_never_leaves_a_job_running(api):
    async def fake(user_id, service_uuid, on_progress):
        raise RuntimeError("secret internals")

    tracker = use_publish(fake)
    headers = await token_for(api, "alice")
    job_id = (await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=headers)).json()["job_id"]
    await finish(tracker)
    body = (await api.get(f"/publish/{job_id}", headers=headers)).json()
    assert body["status"] == "failed" and body["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internals" not in str(body)


async def test_same_user_and_service_share_one_running_job(api):
    gate = asyncio.Event()
    calls = []

    async def fake(user_id, service_uuid, on_progress):
        calls.append(user_id)
        await gate.wait()
        return PublishResult(status="done", mcp_url=MCP_URL, version="1")

    tracker = use_publish(fake)
    alice, bob = await token_for(api, "alice"), await token_for(api, "bob")
    first = (await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=alice)).json()["job_id"]
    again = (await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=alice)).json()["job_id"]
    other = (await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=bob)).json()["job_id"]
    assert first == again and other != first
    gate.set()
    await finish(tracker)
    assert sorted(calls) == ["alice", "bob"]
    # once finished, publishing again starts a new job (e.g. a retry after a failure)
    assert (await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=alice)).json()["job_id"] != first
    await finish(tracker)


async def test_a_job_belongs_to_the_user_who_started_it(api):
    async def fake(user_id, service_uuid, on_progress):
        return PublishResult(status="done", mcp_url=MCP_URL, version="1")

    tracker = use_publish(fake)
    alice, bob = await token_for(api, "alice"), await token_for(api, "bob")
    job_id = (await api.post("/publish", json={"service_uuid": DEMO_UUID}, headers=alice)).json()["job_id"]
    await finish(tracker)
    assert (await api.get(f"/publish/{job_id}", headers=bob)).status_code == 404
    assert (await api.get("/publish/unknown", headers=alice)).status_code == 404


async def test_publish_rejects_a_bad_service_id(api):
    headers = await token_for(api, "alice")
    for bad in ("../x", "", "a b", "x" * 65):
        resp = await api.post("/publish", json={"service_uuid": bad}, headers=headers)
        assert resp.status_code == 422


async def test_finished_jobs_are_dropped_after_the_ttl():
    now = [0.0]

    async def fake(user_id, service_uuid, on_progress):
        return PublishResult(status="done", mcp_url=MCP_URL, version="1")

    tracker = jobs.PublishJobs(publish=fake, ttl=100, clock=lambda: now[0])
    job = tracker.start("alice", DEMO_UUID)
    await finish(tracker)
    assert tracker.get(job.id, "alice") is job
    now[0] = 101
    tracker.start("alice", OTHER_UUID)  # any new start cleans up
    assert tracker.get(job.id, "alice") is None
    await finish(tracker)


async def test_the_default_publish_is_the_real_pipeline(monkeypatch):
    """With no injected function the job runs pipeline.publish.publish."""
    from backend.app.pipeline import publish as publish_module

    calls = []

    async def spy(user_id, service_uuid, on_progress):
        calls.append((user_id, service_uuid))
        return PublishResult(status="done", mcp_url=MCP_URL, version="1")

    monkeypatch.setattr(publish_module, "publish", spy)
    tracker = jobs.PublishJobs()
    tracker.start("alice", DEMO_UUID)
    await finish(tracker)
    assert calls == [("alice", DEMO_UUID)]


# ---- /me/services ----

async def test_me_services_lists_connected_active_and_expired(api, dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")  # in-memory token store + mapping
    directory = factory.get_service_directory()
    directory.add(ServiceInfo(service_uuid=OTHER_UUID, service_name="Lakeside Dental",
                              base_url="http://x.test", oauth=OAuthInfo(auth_url="a", token_url="t")))
    mapping = factory.get_mapping()
    mapping.upsert_connection("alice", DEMO_UUID, "active")    # Demo Bistro is live in the registry
    mapping.upsert_connection("alice", OTHER_UUID, "active")   # connected, nothing published
    mapping.upsert_connection("alice", "33333333-3333-3333-3333-333333333333", "expired")
    mapping.upsert_connection("bob", DEMO_UUID, "active")

    resp = await api.get("/me/services", headers=await token_for(api, "alice"))
    assert resp.status_code == 200
    by_uuid = {s["service_uuid"]: s for s in resp.json()}
    assert set(by_uuid) == {DEMO_UUID, OTHER_UUID, "33333333-3333-3333-3333-333333333333"}  # not bob's
    assert (by_uuid[DEMO_UUID]["service_name"], by_uuid[DEMO_UUID]["status"]) == ("Demo Bistro", "active")
    assert by_uuid[DEMO_UUID]["mcp_url"] == MCP_URL
    assert (by_uuid[OTHER_UUID]["status"], by_uuid[OTHER_UUID]["mcp_url"]) == ("connected", None)
    expired = by_uuid["33333333-3333-3333-3333-333333333333"]
    assert expired["status"] == "expired" and expired["mcp_url"] is None
    assert expired["service_name"] == "33333333-3333-3333-3333-333333333333"  # unknown service: uuid


async def test_me_services_is_empty_for_a_new_user(api):
    resp = await api.get("/me/services", headers=await token_for(api, "newbie"))
    assert resp.status_code == 200 and resp.json() == []


async def test_me_services_failure_is_a_clean_503(api, monkeypatch):
    class Broken:
        def list_for_user(self, user_id):
            raise RuntimeError("db password is hunter2")

    monkeypatch.setattr(factory, "get_mapping", lambda: Broken())
    resp = await api.get("/me/services", headers=await token_for(api, "alice"))
    assert resp.status_code == 503 and "hunter2" not in resp.text
