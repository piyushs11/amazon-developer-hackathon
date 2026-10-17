import logging

from backend.app.deploy import GatewayDeployer
from backend.app.gateway.bundles import get_registry
from backend.tests.dev3_support import (
    DEMO_USER_TOKEN,
    DEMO_UUID,
    bearer,
    connect,
    copy_bundle,
    login,
    rpc,
    upstream,
)
from contracts.models import DeployRequest
from runtime import loader

URL = f"/mcp/{DEMO_UUID}"


async def call(client, token, name, **arguments):
    resp = await client.post(URL, headers=bearer(token),
                             json=rpc("tools/call", {"name": name, "arguments": arguments}))
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


# ---- protocol ----

async def test_initialize_and_list_tools(client):
    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN),
                             json=rpc("initialize", {"protocolVersion": "2025-11-25",
                                                     "capabilities": {},
                                                     "clientInfo": {"name": "t", "version": "1"}}))
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert "tools" in result["capabilities"]
    assert "mcp-session-id" not in resp.headers

    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN),
                             json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202

    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN), json=rpc("tools/list"))
    tools = resp.json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["search_menu", "get_order_status", "place_order"]
    assert tools[1]["inputSchema"]["required"] == ["order_id"]
    assert tools[2]["annotations"]["readOnlyHint"] is False


async def test_unknown_method_and_tool(client):
    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN), json=rpc("resources/list"))
    assert resp.json()["error"]["code"] == -32601
    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN),
                             json=rpc("tools/call", {"name": "nope", "arguments": {}}))
    assert resp.json()["error"]["code"] == -32602


async def test_get_and_batch_rejected(client):
    assert (await client.get(URL, headers=bearer(DEMO_USER_TOKEN))).status_code == 405
    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN), json=[rpc("ping")])
    assert resp.status_code == 400


# ---- identity (C8) ----

async def test_no_auth_401(client):
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}):
        resp = await client.post(URL, headers=headers, json=rpc("tools/list"))
        assert resp.status_code == 401
        assert "www-authenticate" not in resp.headers


async def test_unknown_service_404(client):
    resp = await client.post("/mcp/22222222-2222-2222-2222-222222222222",
                             headers=bearer(DEMO_USER_TOKEN), json=rpc("tools/list"))
    assert resp.status_code == 404


# ---- tool calls ----

async def test_tool_call_with_token(client):
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="A1042")
    assert result["isError"] is False
    assert result["content"][0]["text"] == "Order A1042 is ready for pickup."
    assert result["structuredContent"]["status"] == "ready for pickup"
    assert upstream.calls[-1]["url"] == "http://localhost:9000/orders/A1042"
    assert upstream.calls[-1]["token"] == "demo-token"


async def test_invalid_arguments_are_tool_errors(client):
    result = await call(client, DEMO_USER_TOKEN, "place_order", item="Tiramisu", quantity="two")
    assert result["isError"] is True and "Invalid arguments" in result["content"][0]["text"]
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="A1", extra=1)
    assert result["isError"] is True and "unknown argument" in result["content"][0]["text"]
    assert upstream.calls == []


async def test_not_connected(client):
    token = await login(client, "carol")
    result = await call(client, token, "get_order_status", order_id="A1042")
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Please connect Demo Bistro in MCP Bridge first."


async def test_user_isolation(client, dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")
    alice, bob = await login(client, "alice"), await login(client, "bob")
    await connect("alice")
    await connect("bob")

    a = await call(client, alice, "get_order_status", order_id="A1042")
    b = await call(client, bob, "get_order_status", order_id="A1042")
    assert a["content"][0]["text"] == "Order A1042 is out for delivery."
    assert b["content"][0]["text"] == "Order A1042 is being prepared."

    by_user = {c["user_id"]: c["token"] for c in upstream.calls}
    assert by_user["alice"].startswith("demo-access.alice.")
    assert by_user["bob"].startswith("demo-access.bob.")


async def test_expired_connection_asks_to_reconnect(client, dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")
    from backend.app.auth.factory import get_token_store
    from runtime.tokens import TokenSet

    token = await login(client, "alice")
    await connect("alice")
    get_token_store().put("alice", DEMO_UUID, TokenSet(access_token="x", expires_at=0))
    result = await call(client, token, "get_order_status", order_id="A1042")
    assert result["isError"] is True and "reconnect" in result["content"][0]["text"]


async def test_last_called_at_updated(client):
    from backend.app.auth.factory import get_mapping

    await call(client, DEMO_USER_TOKEN, "search_menu", query="pasta")
    assert get_mapping().get_connection("demo-user", DEMO_UUID).last_called_at is not None


async def test_logs_never_contain_tokens(client, dev3_env, caplog):
    dev3_env(TOKEN_PROVIDER="memory")
    caplog.set_level(logging.DEBUG)
    token = await login(client, "alice")
    await connect("alice")
    await call(client, token, "get_order_status", order_id="A1042")
    upstream_token = upstream.calls[-1]["token"]
    assert "tool_call" in caplog.text
    assert token not in caplog.text and upstream_token not in caplog.text
    assert DEMO_USER_TOKEN not in caplog.text


# ---- versions / deploy ----

async def test_new_version_live_and_broken_version_rejected(client, tmp_path):
    def rename_tool_text(dest):
        ep = dest / "endpoints/get_order_status.py"
        ep.write_text(ep.read_text().replace("Get the status of an order by its ID.",
                                             "V2: order status."))

    v2 = copy_bundle(tmp_path, "v2", edit=rename_tool_text)
    result = await GatewayDeployer().deploy(
        DeployRequest(service_uuid=DEMO_UUID, version="v2", bundle_path=str(v2)))
    assert result.status == "deployed"
    assert result.mcp_url == f"http://gw.test/mcp/{DEMO_UUID}"

    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN), json=rpc("tools/list"))
    assert resp.json()["result"]["tools"][1]["description"] == "V2: order status."

    # Re-deploying the same version is a no-op.
    again = await GatewayDeployer().deploy(
        DeployRequest(service_uuid=DEMO_UUID, version="v2", bundle_path=str(v2)))
    assert again.status == "deployed"

    v3 = copy_bundle(tmp_path, "v3",
                     edit=lambda d: (d / "tools.py").write_text("TOOLS = [this is not python"))
    broken = await GatewayDeployer().deploy(
        DeployRequest(service_uuid=DEMO_UUID, version="v3", bundle_path=str(v3)))
    assert broken.status == "failed"
    assert get_registry().get_active_bundle(DEMO_UUID).version == "v2"
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="A1042")
    assert result["isError"] is False


def test_loader_refuses_other_runtime_version(tmp_path, dev3_env):
    import json

    import pytest

    def bump(dest):
        m = json.loads((dest / "manifest.json").read_text())
        m["runtime_version"] = "999"
        (dest / "manifest.json").write_text(json.dumps(m))

    bad = copy_bundle(tmp_path, "rv", edit=bump)
    with pytest.raises(loader.BundleLoadError, match="runtime_version"):
        loader.load(DEMO_UUID, "rv", str(bad))
