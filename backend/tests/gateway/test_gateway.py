import json
import logging

import pytest

from backend.app.deploy import GatewayDeployer
from backend.app.gateway.bundles import get_registry
from backend.tests.dev3_support import (
    DEMO_USER_TOKEN,
    DEMO_UUID,
    FIXTURE_BUNDLE,
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


async def call(client, user_token, name, **arguments):
    resp = await client.post(URL, headers=bearer(user_token),
                             json=rpc("tools/call", {"name": name, "arguments": arguments}))
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


async def list_tools(client) -> dict:
    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN), json=rpc("tools/list"))
    return {t["name"]: t for t in resp.json()["result"]["tools"]}


# ---- protocol ----

async def test_initialize_and_list_tools(client):
    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN),
                             json=rpc("initialize", {"protocolVersion": "2025-11-25",
                                                     "capabilities": {},
                                                     "clientInfo": {"name": "t", "version": "1"}}))
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["protocolVersion"] == "2025-11-25"
    assert result["serverInfo"]["name"] == "MCP Bridge: Demo Bistro"
    assert "mcp-session-id" not in resp.headers

    resp = await client.post(URL, headers=bearer(DEMO_USER_TOKEN),
                             json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp.status_code == 202

    tools = await list_tools(client)
    assert set(tools) == {"search_menu", "get_order_status", "place_order"}
    assert tools["get_order_status"]["inputSchema"]["required"] == ["order_id"]
    assert tools["get_order_status"]["description"] == "Get the status of an order by its ID."
    assert tools["get_order_status"]["annotations"]["readOnlyHint"] is True
    assert tools["place_order"]["annotations"]["readOnlyHint"] is False
    assert "token" not in tools["place_order"]["inputSchema"]["properties"]


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


# ---- tool calls (Dev 2's generated tools, token set via runtime.auth_context) ----

async def test_tool_call_with_token(client):
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="A1042")
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "ready for pickup"
    assert json.loads(result["content"][0]["text"])["order_id"] == "A1042"
    assert upstream.calls[-1]["url"] == "http://localhost:9000/orders/A1042"
    assert upstream.calls[-1]["token"] == "demo-token"


async def test_upstream_error_is_tool_error(client):
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="NOPE")
    assert result["isError"] is True
    assert result["content"][0]["text"] == "request to get_order_status failed"


async def test_invalid_arguments_are_tool_errors(client):
    result = await call(client, DEMO_USER_TOKEN, "place_order", item="Tiramisu", quantity="two")
    assert result["isError"] is True and "Invalid arguments" in result["content"][0]["text"]
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="A1", extra=1)
    assert result["isError"] is True and "unknown argument" in result["content"][0]["text"]
    assert upstream.calls == []


async def test_llm_supplied_token_is_ignored(client):
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="A1042",
                        token="stolen")
    assert result["isError"] is False
    assert upstream.calls[-1]["token"] == "demo-token"


async def test_not_connected(client):
    token = await login(client, "carol")
    result = await call(client, token, "get_order_status", order_id="A1042")
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Please connect Demo Bistro in MCP Bridge first."
    assert upstream.calls == []


async def test_user_isolation(client, dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")
    alice, bob = await login(client, "alice"), await login(client, "bob")
    await connect("alice")
    await connect("bob")

    a = await call(client, alice, "get_order_status", order_id="A1042")
    b = await call(client, bob, "get_order_status", order_id="A1042")
    assert a["structuredContent"]["status"] == "out for delivery"
    assert b["structuredContent"]["status"] == "being prepared"
    assert upstream.calls[0]["token"].startswith("demo-access.alice.")
    assert upstream.calls[1]["token"].startswith("demo-access.bob.")


async def test_expired_connection_asks_to_reconnect(client, dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")
    from backend.app.auth.factory import get_token_store
    from runtime.tokens import TokenSet

    token = await login(client, "alice")
    await connect("alice")
    get_token_store().put("alice", DEMO_UUID, TokenSet(access_token="x", expires_at=0))
    result = await call(client, token, "get_order_status", order_id="A1042")
    assert result["isError"] is True and "reconnect" in result["content"][0]["text"]


async def test_rejected_token_asks_to_reconnect(client, dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")
    from backend.app.auth.factory import get_token_store
    from runtime.tokens import TokenSet

    token = await login(client, "alice")
    await connect("alice")
    get_token_store().put("alice", DEMO_UUID, TokenSet(access_token="revoked"))
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


# ---- versions / deploy (C5) ----

def _edit_description(dest):
    tool = dest / "get_order_status.py"
    tool.write_text(tool.read_text().replace("Get the status of an order by its ID.",
                                             "V2: order status."))


async def test_new_version_live_and_broken_version_rejected(client, tmp_path):
    v2 = copy_bundle(tmp_path, "a1b2c3d4e5f6", edit=_edit_description)
    result = await GatewayDeployer().deploy(
        DeployRequest(service_uuid=DEMO_UUID, version="a1b2c3d4e5f6", bundle_path=str(v2)))
    assert result.status == "deployed"
    assert result.mcp_url == f"http://gw.test/mcp/{DEMO_UUID}"
    assert (await list_tools(client))["get_order_status"]["description"] == "V2: order status."

    # Re-deploying the same version is a no-op.
    again = await GatewayDeployer().deploy(
        DeployRequest(service_uuid=DEMO_UUID, version="a1b2c3d4e5f6", bundle_path=str(v2)))
    assert again.status == "deployed"

    v3 = copy_bundle(tmp_path, "0123456789ab", edit=lambda d: (d / "place_order.py").write_text(
        "async def place_orderfordemo_bistro(item: str) -> str\n    return 'broken'\n"))
    broken = await GatewayDeployer().deploy(
        DeployRequest(service_uuid=DEMO_UUID, version="0123456789ab", bundle_path=str(v3)))
    assert broken.status == "failed" and "place_order" in broken.error
    assert get_registry().get_active_bundle(DEMO_UUID).version == "a1b2c3d4e5f6"
    result = await call(client, DEMO_USER_TOKEN, "get_order_status", order_id="A1042")
    assert result["isError"] is False


async def test_deploy_missing_folder_fails(dev3_env, tmp_path):
    result = await GatewayDeployer().deploy(
        DeployRequest(service_uuid=DEMO_UUID, version="ffffffffffff",
                      bundle_path=str(tmp_path / "nope")))
    assert result.status == "failed"


def test_loader_rejects_tools_that_take_a_token(tmp_path, dev3_env):
    def add_token_param(dest):
        tool = dest / "search_menu.py"
        tool.write_text(tool.read_text().replace(
            "async def search_menufordemo_bistro(", "async def search_menufordemo_bistro(token: str, "))

    bad = copy_bundle(tmp_path, "tok", edit=add_token_param)
    with pytest.raises(loader.BundleLoadError, match="token"):
        loader.load(DEMO_UUID, "tok", str(bad))


def test_loader_reads_generated_fixture(dev3_env):
    bundle = loader.load(DEMO_UUID, "fixture", str(FIXTURE_BUNDLE))
    assert bundle.service_name == "demo_bistro"
    assert bundle.by_name["get_order_status"].fn.__name__ == "get_order_statusfordemo_bistro"
