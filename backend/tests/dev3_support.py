"""Shared fixtures for Dev 3 tests (auth + gateway). Everything runs in-process:
the mock demo-api and fake OAuth apps are reached through httpx.ASGITransport.

runtime/client.py (Dev 2) may still be empty, so per the plan the hand-written
bundle runs against a STUB call_api installed here.
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI

from contracts.models import ToolResult

ROOT = Path(__file__).resolve().parents[2]
DEMO_UUID = "11111111-1111-1111-1111-111111111111"
DEMO_USER_TOKEN = "test-demo-user-token"
JWT_SECRET = "test-jwt-secret-that-is-at-least-32-bytes"
FIXTURE_BUNDLE = ROOT / "contracts/fixtures/bundle.demo_bistro"


def _load_app(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.app


demo_api_app = _load_app("mock-services/demo-api/main.py", "mock_demo_api")
oauth_app = _load_app("mock-services/oauth/main.py", "mock_oauth")


class UpstreamLog:
    """What the stub call_api sent upstream (method, url, bearer token)."""

    def __init__(self):
        self.calls: list[dict] = []


upstream = UpstreamLog()


async def stub_call_api(ctx, method, path_template, *, path=None, query=None, body=None,
                        headers=None):
    from runtime.tokens import get_token_provider

    token = await get_token_provider().get_valid_token(ctx.user_id, ctx.service_uuid)
    encoded = {k: quote(str(v), safe="") for k, v in (path or {}).items()}
    url = ctx.base_url + path_template.format(**encoded)
    query = {k: v for k, v in (query or {}).items() if v is not None}
    body = {k: v for k, v in (body or {}).items() if v is not None} or None
    upstream.calls.append({"user_id": ctx.user_id, "method": method, "url": url, "token": token})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=demo_api_app)) as client:
        resp = await client.request(method, url, params=query, json=body,
                                    headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 400:
        return ToolResult(text=f"The service answered with an error ({resp.status_code}).",
                          is_error=True)
    data = resp.json()
    if "status" in data and "order_id" in data:
        return ToolResult(text=f"Order {data['order_id']} is {data['status']}.", data=data)
    return ToolResult(text=json.dumps(data)[:200], data=data)


@pytest.fixture(autouse=True)
def stub_runtime_client(monkeypatch):
    from runtime import client

    if not hasattr(client, "call_api"):  # Dev 2's real call_api not merged yet
        monkeypatch.setattr(client, "call_api", stub_call_api, raising=False)
        monkeypatch.setattr(client, "ToolResult", ToolResult, raising=False)
    upstream.calls.clear()


@pytest.fixture
def dev3_env(monkeypatch, tmp_path):
    """Fresh Dev 3 configuration per test. Override env vars before calling `configure`."""
    from backend.app.auth import factory, oauth
    from backend.app.gateway import bundles
    from runtime import loader

    env = {
        "MODE": "local",
        "TOKEN_PROVIDER": "fake",
        "REGISTRY": "memory",
        "IDENTITY": "jwt,fixed",
        "DEMO_USER_TOKEN": DEMO_USER_TOKEN,
        "PLATFORM_JWT_SECRET": JWT_SECRET,
        "OAUTH_STATE_SECRET": "test-state-secret",
        "TOKEN_ENC_KEY": "test-enc-key",
        "GATEWAY_URL": "http://gw.test",
        "API_URL": "http://api.test",
        "FRONTEND_URL": "http://ui.test",
        "BUNDLE_CACHE_DIR": str(tmp_path / "cache"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("UPSTREAM_REWRITES", raising=False)

    def configure(**overrides):
        for key, value in overrides.items():
            monkeypatch.setenv(key, value)
        factory.reset()
        bundles.reset()
        loader.clear_cache()
        oauth.set_http_transport(httpx.ASGITransport(app=oauth_app))
        factory.configure()

    configure()
    yield configure
    factory.reset()
    bundles.reset()
    loader.clear_cache()
    oauth.set_http_transport(None)


@pytest.fixture
def app(dev3_env):
    from backend.app.auth.router import router as auth_router
    from backend.app.gateway import router as gateway_router

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(gateway_router)
    return app


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://gw.test") as c:
        yield c


def rpc(method: str, params: dict | None = None, rpc_id: int = 1) -> dict:
    msg = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}


async def login(client, username: str) -> str:
    resp = await client.post("/auth/demo-login", json={"username": username})
    assert resp.status_code == 200
    return resp.json()["user_token"]


async def connect(user_id: str, service_uuid: str = DEMO_UUID) -> None:
    """Run the full fake OAuth flow (A1–A5) for a user, in-process."""
    from backend.app.auth.oauth import build_auth_url, handle_callback

    auth_url = build_auth_url(user_id, service_uuid)
    path = auth_url.split("://", 1)[1].split("/", 1)[1]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=oauth_app),
                                 base_url="http://oauth.test") as c:
        resp = await c.get("/" + path)
    assert resp.status_code in (302, 307)
    location = httpx.URL(resp.headers["location"])
    result = await handle_callback(location.params["code"], location.params["state"])
    assert result.status == "ok", result


def copy_bundle(tmp_path: Path, version: str, *, edit=None) -> Path:
    """A copy of the fixture bundle as a new version, optionally edited."""
    dest = tmp_path / "bundles" / DEMO_UUID / version
    shutil.copytree(FIXTURE_BUNDLE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = json.loads((dest / "manifest.json").read_text())
    manifest["version"] = version
    (dest / "manifest.json").write_text(json.dumps(manifest))
    if edit:
        edit(dest)
    return dest
