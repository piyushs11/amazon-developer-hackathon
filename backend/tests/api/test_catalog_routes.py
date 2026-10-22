"""/resolve-service, /services/{uuid} and DELETE /me/services/{uuid} (REGISTRY=memory fixtures)."""
import pytest

from backend.app.auth import factory
from backend.tests.dev3_support import DEMO_UUID, bearer, connect, login


@pytest.mark.parametrize("method, path, body", [
    ("POST", "/resolve-service", {"query": "demobistro.test"}),
    ("GET", f"/services/{DEMO_UUID}", None),
    ("DELETE", f"/me/services/{DEMO_UUID}", None),
])
async def test_new_routes_need_a_token(api, method, path, body):
    resp = await api.request(method, path, json=body)
    assert resp.status_code == 401 and "www-authenticate" not in resp.headers


@pytest.mark.parametrize("body", [
    {"query": "https://www.demobistro.test/menu"},
    {"query": "Demo Bistro"},
    {"input_type": "url", "webpage_url": "demobistro.test"},
    {"input_type": "name_location", "name_location": {"name": "bistro", "city": "Chicago"}},
])
async def test_resolve_finds_demo_bistro(api, body):
    resp = await api.post("/resolve-service", json=body, headers=bearer(await login(api, "alice")))
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["service"] == {"service_uuid": DEMO_UUID, "service_name": "Demo Bistro",
                                      "domain": "demobistro.test"}


async def test_resolve_not_found_and_bad_input(api):
    headers = bearer(await login(api, "alice"))
    resp = await api.post("/resolve-service", json={"query": "pizzapalace.com"}, headers=headers)
    assert resp.json() == {"status": "not_found", "service": None, "candidates": None}
    resp = await api.post("/resolve-service", json={"input_type": "url"}, headers=headers)
    assert resp.status_code == 422


async def test_service_details(api):
    headers = bearer(await login(api, "alice"))
    body = (await api.get(f"/services/{DEMO_UUID}", headers=headers)).json()
    assert body["service_name"] == "Demo Bistro" and body["domain"] == "demobistro.test"
    assert body["published"] is True  # the memory registry starts with the hand-written bundle
    assert body["mcp_url"].endswith(f"/mcp/{DEMO_UUID}")
    assert {t["name"]: t["read_only"] for t in body["tools"]} == {
        "search_menu": True, "get_order_status": True, "place_order": False}
    assert (await api.get("/services/nope", headers=headers)).status_code == 404


async def test_disconnect_removes_the_token(api):
    headers = bearer(await login(api, "alice"))
    await connect("alice")
    assert (await api.delete(f"/me/services/{DEMO_UUID}", headers=headers)).status_code == 204
    assert factory.get_token_store().get("alice", DEMO_UUID) is None
    assert factory.get_mapping().get_connection("alice", DEMO_UUID).status == "revoked"
    services = (await api.get("/me/services", headers=headers)).json()
    assert [s["status"] for s in services] == ["revoked"]
    assert (await api.delete(f"/me/services/{DEMO_UUID}", headers=headers)).status_code == 404
