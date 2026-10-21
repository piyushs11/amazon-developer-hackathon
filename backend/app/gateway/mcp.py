"""MCP JSON-RPC methods for one (user, service) request. Stateless, plain JSON.

Handles: initialize, notifications/*, ping, tools/list, tools/call.

A tools/call runs one tool of the published bundle for the calling user:
    token  <- TokenProvider.get_valid_token(user_id, service_uuid)   (refreshed if needed)
    result <- runtime.auth_context.call_with_token(tool_fn, token, args)  (Dev 2)
The tool reads the token with get_current_token() just before its API call; it never sees
user_id and the LLM never supplies the token.
"""
import asyncio
import json
import logging
import time
import uuid

import jsonschema

from backend.app.auth.factory import get_mapping
from runtime.auth_context import call_with_token
from runtime.loader import LoadedBundle, Tool
from runtime.tokens import TokenError, get_token_provider

log = logging.getLogger("mcp_bridge.gateway")

SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SERVER_VERSION = "0.1.0"
CALL_TIMEOUT_SECONDS = 30.0

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Request:
    """Everything a method needs; built fresh for every HTTP request."""

    def __init__(self, user_id: str, service_uuid: str, service_name: str, bundle: LoadedBundle):
        self.user_id = user_id
        self.service_uuid = service_uuid
        self.service_name = service_name  # display name, e.g. "Demo Bistro"
        self.bundle = bundle
        self.request_id = uuid.uuid4().hex[:16]


async def dispatch(req: Request, method: str, params: dict) -> dict:
    if method == "initialize":
        return _initialize(req, params)
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [_tool_entry(tool) for tool in req.bundle.tools]}
    if method == "tools/call":
        return await _call_tool(req, params)
    raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")


def _initialize(req: Request, params: dict) -> dict:
    asked = params.get("protocolVersion")
    version = asked if asked in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": f"MCP Bridge: {req.service_name}", "version": SERVER_VERSION},
    }


def _tool_entry(tool: Tool) -> dict:
    entry = {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}
    if tool.read_only is not None:
        entry["annotations"] = {"readOnlyHint": tool.read_only}
    return entry


def _result(text: str, data: dict | None = None, is_error: bool = False) -> dict:
    out: dict = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if isinstance(data, dict):
        out["structuredContent"] = data
    return out


def _argument_error(tool: Tool, args: dict) -> str | None:
    schema = tool.input_schema
    unknown = set(args) - set(schema.get("properties", {}))
    if unknown:
        return f"unknown argument(s): {', '.join(sorted(unknown))}"
    error = jsonschema.exceptions.best_match(
        jsonschema.Draft202012Validator(schema).iter_errors(args)
    )
    return error.message if error else None


async def _call_tool(req: Request, params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    if not isinstance(name, str) or name not in req.bundle.by_name:
        raise RpcError(INVALID_PARAMS, f"unknown tool: {name}")
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    tool = req.bundle.by_name[name]

    started = time.monotonic()
    result = await _run_tool(req, tool, args)
    log.info(
        "tool_call request_id=%s service_uuid=%s user_id=%s tool=%s duration_ms=%d is_error=%s",
        req.request_id, req.service_uuid, req.user_id, name,
        (time.monotonic() - started) * 1000, result["isError"],
    )
    try:
        await asyncio.to_thread(get_mapping().touch, req.user_id, req.service_uuid)
    except Exception:  # noqa: BLE001 — last_called_at is cosmetic; never fail the call
        log.warning("touch failed request_id=%s", req.request_id)
    return result


async def _run_tool(req: Request, tool: Tool, args: dict) -> dict:
    not_connected = _result(f"Please connect {req.service_name} in MCP Bridge first.",
                            is_error=True)
    connection = await asyncio.to_thread(get_mapping().get_connection, req.user_id, req.service_uuid)
    if connection is None or connection.status != "active":
        return not_connected

    args = {k: v for k, v in args.items() if k != "token"}  # the LLM never supplies the token
    problem = _argument_error(tool, args)
    if problem:
        return _result(f"Invalid arguments for {tool.name}: {problem}", is_error=True)

    try:
        token = await get_token_provider().get_valid_token(req.user_id, req.service_uuid)
    except TokenError as exc:
        if exc.code == TokenError.NOT_CONNECTED:
            return not_connected
        return _result(
            f"Your {req.service_name} connection expired. Please reconnect it in MCP Bridge.",
            is_error=True,
        )

    try:
        out = await call_with_token(tool.fn, token, args, CALL_TIMEOUT_SECONDS)
    except TimeoutError:
        return _result(f"{req.service_name} took too long to answer.", is_error=True)
    except Exception as exc:  # noqa: BLE001 — never leak stack traces (or the token) to the caller
        log.error("tool_failed request_id=%s tool=%s error=%s",
                  req.request_id, tool.name, type(exc).__name__)
        return _result(f"Something went wrong talking to {req.service_name}.", is_error=True)
    return _from_tool_output(req, out)


def _from_tool_output(req: Request, out) -> dict:
    """Generated tools return a JSON string: the API response, or {"message", "status"} on failure."""
    data = out
    if isinstance(out, str):
        try:
            data = json.loads(out)
        except ValueError:
            return _result(out)
    if isinstance(data, dict) and set(data) == {"message", "status"}:
        status = data["status"]
        if status is None or (isinstance(status, int) and not 200 <= status < 300):
            if status in (401, 403):
                return _result(
                    f"{req.service_name} rejected the connection. Please reconnect it in MCP Bridge.",
                    is_error=True,
                )
            return _result(str(data["message"]), data, is_error=True)
    text = out if isinstance(out, str) else json.dumps(data, default=str)
    return _result(text, data if isinstance(data, dict) else None)
