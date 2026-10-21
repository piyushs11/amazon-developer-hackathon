"""The official MCP client (pinned SDK, Streamable HTTP) talks to our hand-rolled gateway.

This is the check that MCP Inspector / Alexa+ style clients can use /mcp/{uuid}.
"""
import json

import httpx2
import pytest

from backend.tests.dev3_support import DEMO_USER_TOKEN, DEMO_UUID

mcp_client = pytest.importorskip("mcp.client.streamable_http")
from mcp.client.session import ClientSession


async def test_official_client_lists_and_calls(app):
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        headers={"Authorization": f"Bearer {DEMO_USER_TOKEN}"},
    )
    async with http, mcp_client.streamable_http_client(
        f"http://gw.test/mcp/{DEMO_UUID}", http_client=http
    ) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "MCP Bridge: Demo Bistro"

            listed = await session.list_tools()
            assert {t.name for t in listed.tools} == {
                "search_menu", "get_order_status", "place_order"
            }

            result = await session.call_tool("get_order_status", {"order_id": "A1042"})
            assert not result.is_error
            assert json.loads(result.content[0].text)["status"] == "ready for pickup"
