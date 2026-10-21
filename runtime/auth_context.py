"""Per-call slots: the token and the service's base URL.

The caller (gateway / verifier) runs a tool inside `use_token(token)` / `use_base_url(url)`;
the generated tool calls `get_current_token()` and `get_current_base_url()`. A ContextVar is
per async task, so concurrent calls for different users each see only their own values.

The base URL is NOT written into generated tools: it comes from the registry at call time
(with UPSTREAM_REWRITES applied by the caller), so one bundle works on a laptop, in Docker
and on AWS.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar

_current_token: ContextVar[str | None] = ContextVar("current_token", default=None)
_current_base_url: ContextVar[str | None] = ContextVar("current_base_url", default=None)


def get_current_token() -> str:
    token = _current_token.get()
    if not token:
        raise RuntimeError("no token set for this call")
    return token


def get_current_base_url() -> str:
    base_url = _current_base_url.get()
    if not base_url:
        raise RuntimeError("no base URL set for this call")
    return base_url


@contextmanager
def use_token(token: str):
    """Make `token` the current token for the code run inside the block (always reset after)."""
    reset = _current_token.set(token)
    try:
        yield
    finally:
        _current_token.reset(reset)


@contextmanager
def use_base_url(base_url: str):
    """Make `base_url` the current service base URL for the code run inside the block."""
    reset = _current_base_url.set(base_url.rstrip("/"))
    try:
        yield
    finally:
        _current_base_url.reset(reset)


async def call_with_token(
    fn: Callable[..., Awaitable], token: str, args: dict, timeout: float,
    base_url: str | None = None,
):
    """Run `fn(**args)` with `token` (and `base_url`, if given) in the slots.

    Fails with TimeoutError after `timeout`.
    """
    with use_token(token):
        if base_url:
            with use_base_url(base_url):
                return await asyncio.wait_for(fn(**args), timeout)
        return await asyncio.wait_for(fn(**args), timeout)
