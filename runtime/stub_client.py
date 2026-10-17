"""TEMPORARY stand-in for Dev 2's runtime/client.py (C4), so the gateway can serve
the hand-written bundle before the real call_api lands.

install_if_missing() is called at app startup; it does nothing once
runtime.client defines call_api. Delete this file after Dev 2's PR merges.
"""
import logging
from urllib.parse import quote

import httpx

from contracts.models import ToolResult

log = logging.getLogger("mcp_bridge.runtime")
MAX_TEXT = 300


async def call_api(ctx, method: str, path_template: str, *, path: dict | None = None,
                   query: dict | None = None, body: dict | None = None,
                   headers: dict | None = None) -> ToolResult:
    from runtime.tokens import get_token_provider

    token = await get_token_provider().get_valid_token(ctx.user_id, ctx.service_uuid)
    encoded = {k: quote(str(v), safe="") for k, v in (path or {}).items()}
    url = ctx.base_url.rstrip("/") + path_template.format(**encoded)
    query = {k: v for k, v in (query or {}).items() if v is not None}
    body = {k: v for k, v in (body or {}).items() if v is not None} or None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.request(
                method, url, params=query, json=body,
                headers={**(headers or {}), "Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        return ToolResult(text="The service could not be reached.", is_error=True)
    if resp.status_code == 401:
        return ToolResult(text="The service rejected the connection. Please reconnect.",
                          is_error=True)
    if resp.status_code >= 400:
        return ToolResult(text=f"The service answered with an error ({resp.status_code}).",
                          is_error=True)
    data = resp.json() if resp.content else {}
    return ToolResult(text=_speakable(data)[:MAX_TEXT], data=data if isinstance(data, dict) else
                      {"items": data})


def _speakable(data) -> str:
    if isinstance(data, dict):
        if "order_id" in data and "status" in data:
            return f"Order {data['order_id']} is {data['status']}."
        if isinstance(data.get("results"), list):
            names = [r.get("name") for r in data["results"] if isinstance(r, dict)][:5]
            return f"I found: {', '.join(names)}." if names else "I found nothing."
        return ", ".join(f"{k}: {v}" for k, v in list(data.items())[:5])
    return str(data)


def install_if_missing() -> bool:
    from runtime import client

    if hasattr(client, "call_api"):
        return False
    client.call_api = call_api
    client.ToolResult = ToolResult
    log.warning("runtime.client has no call_api yet: using runtime/stub_client.py")
    return True
