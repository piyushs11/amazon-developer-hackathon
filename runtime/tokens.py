
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

REFRESH_MARGIN_SECONDS = 60


class TokenSet(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None  # unix seconds; None = never expires

    def expiring(self, margin: float = REFRESH_MARGIN_SECONDS) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at - margin


class TokenError(Exception):
    """Raised by providers; the gateway turns it into a spoken 'please (re)connect'."""

    NOT_CONNECTED = "NOT_CONNECTED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TokenStore(Protocol):
    def put(self, user_id: str, service_uuid: str, tokens: TokenSet) -> None: ...
    def get(self, user_id: str, service_uuid: str) -> TokenSet | None: ...
    def delete(self, user_id: str, service_uuid: str) -> None: ...


Refresher = Callable[[str, str], Awaitable[TokenSet]]  # (service_uuid, refresh_token) -> new tokens


class FakeTokenProvider:
    """TOKEN_PROVIDER=fake: every user gets the token demo-api accepts."""

    async def get_valid_token(self, user_id: str, service_uuid: str) -> str:
        return "demo-token"


class StoreTokenProvider:
    """TOKEN_PROVIDER=local|secrets: reads the vault, refreshes tokens that expire within 60s."""

    def __init__(self, store: TokenStore, refresher: Refresher):
        self._store = store
        self._refresher = refresher

    async def get_valid_token(self, user_id: str, service_uuid: str) -> str:
        # Stores may block (Postgres, Secrets Manager): keep them off the event loop.
        tokens = await asyncio.to_thread(self._store.get, user_id, service_uuid)
        if tokens is None:
            raise TokenError(TokenError.NOT_CONNECTED, "This account isn't connected yet.")
        if not tokens.expiring():
            return tokens.access_token
        if not tokens.refresh_token:
            raise TokenError(TokenError.TOKEN_EXPIRED, "The connection expired.")
        try:
            new = await self._refresher(service_uuid, tokens.refresh_token)
        except Exception as exc:  # any refresh failure means the user must reconnect
            raise TokenError(TokenError.TOKEN_EXPIRED, "The connection expired.") from exc
        if new.refresh_token is None:  # providers may omit it on refresh
            new = new.model_copy(update={"refresh_token": tokens.refresh_token})
        await asyncio.to_thread(self._store.put, user_id, service_uuid, new)
        return new.access_token


_provider = None


def set_token_provider(provider) -> None:
    """Called once at app startup (see backend/app/auth/factory.py)."""
    global _provider
    _provider = provider


def get_token_provider():
    global _provider
    if _provider is None:
        kind = os.getenv("TOKEN_PROVIDER", "fake")
        if kind != "fake":
            raise RuntimeError(
                f"TOKEN_PROVIDER={kind} needs the app to call set_token_provider() at startup"
            )
        _provider = FakeTokenProvider()
    return _provider
"""Dev 3: TokenProvider implementations (C4)."""
#reads tokens from the auth vault for the service

