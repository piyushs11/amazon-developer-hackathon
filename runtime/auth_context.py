"""Per-call token slot: the LLM never sees the token, tools read it just before the API call.

The caller (gateway / verifier) runs a tool inside `use_token(token)`; the generated tool
calls `get_current_token()`. A ContextVar is per async task, so concurrent calls for
different users each see only their own token.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar

_current_token: ContextVar[str | None] = ContextVar("current_token", default=None)


def get_current_token() -> str:
    token = _current_token.get()
    if not token:
        raise RuntimeError("no token set for this call")
    return token


@contextmanager
def use_token(token: str):
    """Make `token` the current token for the code run inside the block (always reset after)."""
    reset = _current_token.set(token)
    try:
        yield
    finally:
        _current_token.reset(reset)


async def call_with_token(fn: Callable[..., Awaitable], token: str, args: dict, timeout: float):
    """Run `fn(**args)` with `token` in the slot, failing with TimeoutError after `timeout`."""
    with use_token(token):
        return await asyncio.wait_for(fn(**args), timeout)
