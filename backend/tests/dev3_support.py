"""Shared fixtures for Dev 3 tests (auth + gateway). Everything runs in-process:
the mock demo-api and fake OAuth apps are reached through httpx.ASGITransport.

The bundle is Dev 2's generated Demo Bistro bundle. Its tools call the base URL the gateway
gives them (the registry's http://localhost:9000) with httpx; `route_upstream` sends that traffic to the demo-api
app in-process and records each request (method, url, bearer token).
"""
import importlib.util
import shutil
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

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
    """What the generated tools sent to the demo API (method, url, bearer token)."""

    def __init__(self):
        self.calls: list[dict] = []


upstream = UpstreamLog()
_RealAsyncClient = httpx.AsyncClient


class _DemoApiTransport(httpx.ASGITransport):
    def __init__(self):
        super().__init__(app=demo_api_app)

    async def handle_async_request(self, request):
        upstream.calls.append({
            "method": request.method,
            "url": str(request.url),
            "token": request.headers.get("authorization", "").removeprefix("Bearer "),
        })
        return await super().handle_async_request(request)


class _RoutedAsyncClient(_RealAsyncClient):
    """httpx.AsyncClient() with no transport (what generated tools use) -> demo-api app."""

    def __init__(self, *args, **kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = _DemoApiTransport()
        super().__init__(*args, **kwargs)


@pytest.fixture(autouse=True)
def route_upstream(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _RoutedAsyncClient)
    upstream.calls.clear()


@pytest.fixture
def dev3_env(monkeypatch):
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
    shutil.copytree(FIXTURE_BUNDLE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.md"))
    if edit:
        edit(dest)
    return dest
