"""Upstream OAuth A1–A5: authorize URL, callback (code exchange + store), refresh.

Dev 4 wires these into GET /oauth/start and GET /oauth/callback.
"""
import time
from typing import Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from backend.app.auth.settings import get_settings, rewrite
from backend.app.auth.state import StateError, sign_state, verify_state
from runtime.tokens import TokenSet

_transport: httpx.AsyncBaseTransport | None = None  # tests inject an ASGI transport


class OAuthError(Exception):
    pass


class CallbackResult(BaseModel):
    status: Literal["ok", "error"]
    user_id: str | None = None
    service_uuid: str | None = None
    error: str | None = None  # short, safe to show; never contains tokens


def set_http_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def redirect_uri() -> str:
    return f"{get_settings().api_url}/oauth/callback"


def _service(service_uuid: str):
    from backend.app.auth.factory import get_service_directory

    info = get_service_directory().get(service_uuid)
    if info is None:
        raise OAuthError("unknown service")
    if info.oauth is None:
        raise OAuthError("service does not use OAuth")
    return info


# ---- A1 ----

def build_auth_url(user_id: str, service_uuid: str) -> str:
    s = get_settings()
    info = _service(service_uuid)
    query = {
        "client_id": s.oauth_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(info.oauth.scopes),
        "state": sign_state(user_id, service_uuid),
        "login_hint": user_id,  # lets the fake provider pick a per-user demo account
    }
    auth_url = rewrite(info.oauth.auth_url, s.authorize_rewrites)
    sep = "&" if "?" in auth_url else "?"
    return f"{auth_url}{sep}{urlencode(query)}"


# ---- A3–A5 ----

async def handle_callback(code: str, state: str) -> CallbackResult:
    """Never raises: the route turns the result into a redirect to the frontend."""
    from backend.app.auth.factory import get_mapping, get_token_store

    try:
        user_id, service_uuid = verify_state(state)
    except StateError as exc:
        return CallbackResult(status="error", error=str(exc))
    try:
        info = _service(service_uuid)
        tokens = await _token_request(info.oauth.token_url, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(),
        })
    except OAuthError as exc:
        return CallbackResult(status="error", user_id=user_id, service_uuid=service_uuid,
                              error=str(exc))
    get_token_store().put(user_id, service_uuid, tokens)
    get_mapping().upsert_connection(user_id, service_uuid, "active")
    return CallbackResult(status="ok", user_id=user_id, service_uuid=service_uuid)


def callback_redirect(result: CallbackResult) -> str:
    return f"{get_settings().frontend_url}/connect/done?{urlencode({'status': result.status})}"


# ---- refresh (used by StoreTokenProvider) ----

async def refresh(service_uuid: str, refresh_token: str) -> TokenSet:
    info = _service(service_uuid)
    tokens = await _token_request(info.oauth.token_url, {
        "grant_type": "refresh_token", "refresh_token": refresh_token,
    })
    if tokens.refresh_token is None:
        tokens = tokens.model_copy(update={"refresh_token": refresh_token})
    return tokens


async def _token_request(token_url: str, form: dict) -> TokenSet:
    s = get_settings()
    form = {**form, "client_id": s.oauth_client_id, "client_secret": s.oauth_client_secret}
    url = rewrite(token_url, s.upstream_rewrites)
    try:
        async with httpx.AsyncClient(timeout=15, transport=_transport) as client:
            resp = await client.post(url, data=form, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OAuthError("could not reach the token endpoint") from exc
    if resp.status_code >= 400:
        raise OAuthError(f"token endpoint returned {resp.status_code}")
    body = resp.json()
    access = body.get("access_token")
    if not access:
        raise OAuthError("no access token in provider response")
    expires_in = body.get("expires_in")
    return TokenSet(
        access_token=access,
        refresh_token=body.get("refresh_token"),
        expires_at=time.time() + float(expires_in) if expires_in else None,
    )
