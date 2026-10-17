"""Dev 2: call_api(), the runtime pipeline that runs a stored tool for one user (C4).

    call_api(ctx, tool_name, args)
      token   <- the user's token for this service (token_fetcher; the LLM never supplies it)
      version <- the latest stored bundle version of the service
      tool    <- <tool_name>.py read from storage, turned into a function by tool_loader
      result  <- the tool run with the token set just before its API call

The result is returned exactly as the tool produced it (a JSON string); the calling LLM does
any post-processing. Failures come back as the same failure JSON the generated tools use:
{"message": "...", "status": <code>}.
"""

import inspect
import json
import logging
import re
from collections.abc import Callable

from pydantic import BaseModel

from runtime.auth_context import call_with_token

log = logging.getLogger(__name__)

TIMEOUT = 10
_TOOL = re.compile(r"^[a-z_][a-z0-9_]*$")
_UUID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class CallContext(BaseModel):
    """Built by the gateway for every request (user from the caller's token, service from the URL)."""

    user_id: str
    service_uuid: str
    request_id: str = ""


# Immutable bundle versions never change, so a loaded tool function is cached for good.
_LOADED: dict[tuple[str, str, str], Callable] = {}


def _failure(message: str, status: int) -> str:
    return json.dumps({"message": message, "status": status})


def _no_loader(source: str, tool_name: str) -> Callable:
    raise NotImplementedError("tool loader not wired up (waiting for Dev 3's runtime/loader.py)")


def _default_storage():
    from backend.app.storage.add_n_read_mcp_tool import get_storage

    return get_storage()


def _default_token_fetcher():
    from backend.app.storage.read_cred_tokens import get_user_token

    return get_user_token


async def call_api(
    ctx: CallContext, tool_name: str, args: dict | None, *, storage=None, token_fetcher=None,
    tool_loader: Callable[[str, str], Callable] | None = None, timeout: float = TIMEOUT,
) -> str:
    """Run `tool_name` of `ctx.service_uuid` for `ctx.user_id`. Never raises."""
    token = None
    try:
        if not _TOOL.match(str(tool_name)) or not _UUID.match(ctx.service_uuid):
            return _failure("Unknown tool.", 404)

        # The token is checked first so an unconnected user learns nothing about the service.
        token = (token_fetcher or _default_token_fetcher())(ctx.user_id, ctx.service_uuid)
        if inspect.isawaitable(token):
            token = await token
        if not token:
            return _failure("Please connect this service in MCP Bridge first.", 401)

        storage = storage or _default_storage()
        version = storage.get_latest(ctx.service_uuid)
        if version is None:
            return _failure("This service isn't published yet.", 404)

        key = (ctx.service_uuid, version, tool_name)
        fn = _LOADED.get(key)
        if fn is None:
            source = storage.read_file(ctx.service_uuid, version, f"{tool_name}.py")
            if source is None:
                return _failure(f"Unknown tool: {tool_name}.", 404)
            fn = (tool_loader or _no_loader)(source, tool_name)
            _LOADED[key] = fn

        clean_args = {k: v for k, v in (args or {}).items() if k != "token"}  # the LLM never sets it
        log.info(
            "call_api request=%s service=%s version=%s tool=%s args=%s",
            ctx.request_id, ctx.service_uuid, version, tool_name, sorted(clean_args),
        )
        result = await call_with_token(fn, token, clean_args, timeout)
        return result if isinstance(result, str) else json.dumps(result, default=str)
    except NotImplementedError as e:
        return _failure(str(e), 501)
    except TimeoutError:
        return _failure(f"The {tool_name} request timed out.", 504)
    except Exception as e:  # noqa: BLE001 - never leak a stack trace or the token to the caller
        detail = str(e).replace(token, "***") if token else str(e)
        return _failure(f"{tool_name} failed: {type(e).__name__}: {detail[:200]}", 500)
