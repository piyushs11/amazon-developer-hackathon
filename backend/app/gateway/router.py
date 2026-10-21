"""POST /mcp/{service_uuid}: the URL picks the service, the bearer token picks the user.

Stateless Streamable HTTP: every POST gets a plain application/json answer, no
sessions, no SSE stream (so GET and DELETE are 405).
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from backend.app.auth.factory import get_identity, get_service_directory
from backend.app.auth.identity import bearer_token
from backend.app.auth.settings import get_settings, rewrite
from backend.app.gateway import mcp
from backend.app.gateway.bundles import get_registry
from runtime import loader

log = logging.getLogger("mcp_bridge.gateway")
router = APIRouter(tags=["gateway"])


def _display_name(service_uuid: str, bundle: loader.LoadedBundle) -> str:
    """"Demo Bistro" from the service directory; falls back to the bundle's slug."""
    try:
        info = get_service_directory().get(service_uuid)
    except Exception:  # noqa: BLE001 — a name lookup must never fail the call
        info = None
    if info is not None:
        return info.service_name
    return (bundle.service_name or "this service").replace("_", " ").title()


def _rpc_error(rpc_id, code: int, message: str, status: int = 200) -> JSONResponse:
    body = {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}
    return JSONResponse(body, status_code=status)


@router.post("/mcp/{service_uuid}")
async def mcp_endpoint(service_uuid: str, request: Request) -> Response:
    # 1. Who is calling? Bare 401 (no WWW-Authenticate) before anything else.
    token = bearer_token(request)
    user_id = await get_identity().user_from_token(token) if token else None
    if not user_id:
        return Response(status_code=401)

    version_header = request.headers.get("mcp-protocol-version")
    if version_header and version_header not in mcp.SUPPORTED_PROTOCOL_VERSIONS:
        return _rpc_error(None, mcp.INVALID_REQUEST, "unsupported MCP-Protocol-Version", 400)

    # 2. Which bundle?
    active = await asyncio.to_thread(get_registry().get_active_bundle, service_uuid)
    if active is None:
        return JSONResponse({"error": "unknown service"}, status_code=404)

    # 3. Parse JSON-RPC.
    try:
        msg = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _rpc_error(None, mcp.PARSE_ERROR, "parse error", 400)
    if isinstance(msg, list):
        return _rpc_error(None, mcp.INVALID_REQUEST, "batch requests are not supported", 400)
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_error(None, mcp.INVALID_REQUEST, "invalid request", 400)
    if "method" not in msg:  # a response from the client (we never send requests): accept
        return Response(status_code=202)
    if "id" not in msg:  # notification, e.g. notifications/initialized
        return Response(status_code=202)
    rpc_id, method, params = msg["id"], msg["method"], msg.get("params") or {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return _rpc_error(rpc_id, mcp.INVALID_REQUEST, "invalid request")

    # 4. Load the bundle (cached by uuid + version) and run the method.
    try:
        bundle = await asyncio.to_thread(
            loader.load, service_uuid, active.version, active.bundle_path
        )
    except loader.BundleLoadError as exc:
        log.error("bundle_load_failed service_uuid=%s version=%s error=%s",
                  service_uuid, active.version, exc)
        return _rpc_error(rpc_id, mcp.INTERNAL_ERROR, "service is temporarily unavailable")

    service_name = await asyncio.to_thread(_display_name, service_uuid, bundle)
    # The tools take their base URL from here, not from their code. In Docker the registry says
    # http://localhost:9000; UPSTREAM_REWRITES turns that into http://demo-api:9000.
    base_url = rewrite(active.base_url, get_settings().upstream_rewrites)
    req = mcp.Request(user_id, service_uuid, service_name, bundle, base_url)
    try:
        result = await mcp.dispatch(req, method, params)
    except mcp.RpcError as exc:
        return _rpc_error(rpc_id, exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 — never leak stack traces to the caller
        log.error("rpc_failed request_id=%s error=%s", req.request_id, type(exc).__name__)
        return _rpc_error(rpc_id, mcp.INTERNAL_ERROR, "internal error")
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})


@router.api_route("/mcp/{service_uuid}", methods=["GET", "DELETE"])
async def mcp_no_stream(service_uuid: str) -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})
