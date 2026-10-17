import time

import psycopg
import pytest

from backend.app.auth.factory import get_mapping, get_token_store
from backend.app.auth.oauth import build_auth_url, callback_redirect, handle_callback
from backend.app.auth.vault import InMemoryTokenStore, LocalTokenStore
from backend.tests.dev3_support import DEMO_UUID, connect
from runtime.tokens import StoreTokenProvider, TokenError, TokenSet


def test_auth_url_has_signed_state_and_hint(dev3_env):
    url = build_auth_url("alice", DEMO_UUID)
    assert url.startswith("http://localhost:9100/authorize?")
    assert "login_hint=alice" in url and "state=" in url
    assert "redirect_uri=http%3A%2F%2Fapi.test%2Foauth%2Fcallback" in url


async def test_oauth_roundtrip_stores_tokens_and_mapping(dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")
    await connect("alice")
    tokens = get_token_store().get("alice", DEMO_UUID)
    assert tokens.access_token.startswith("demo-access.alice.")
    assert tokens.refresh_token and tokens.expires_at > time.time()
    row = get_mapping().get_connection("alice", DEMO_UUID)
    assert row.status == "active"


async def test_callback_with_bad_state_is_error(dev3_env):
    result = await handle_callback("code", "bad.state")
    assert result.status == "error"
    assert callback_redirect(result) == "http://ui.test/connect/done?status=error"


async def test_refresh_when_expiring(dev3_env):
    dev3_env(TOKEN_PROVIDER="memory")
    await connect("bob")
    store = get_token_store()
    old = store.get("bob", DEMO_UUID)
    store.put("bob", DEMO_UUID, old.model_copy(update={"expires_at": time.time() + 30}))

    from runtime.tokens import get_token_provider

    token = await get_token_provider().get_valid_token("bob", DEMO_UUID)
    assert token != old.access_token and token.startswith("demo-access.bob.")
    assert store.get("bob", DEMO_UUID).expires_at > time.time() + 60


async def test_failed_refresh_means_expired():
    store = InMemoryTokenStore()
    store.put("u", "s", TokenSet(access_token="a", refresh_token="r", expires_at=time.time()))

    async def broken(service_uuid, refresh_token):
        raise RuntimeError("provider down")

    with pytest.raises(TokenError) as err:
        await StoreTokenProvider(store, broken).get_valid_token("u", "s")
    assert err.value.code == TokenError.TOKEN_EXPIRED
    with pytest.raises(TokenError) as err:
        await StoreTokenProvider(store, broken).get_valid_token("nobody", "s")
    assert err.value.code == TokenError.NOT_CONNECTED


def _postgres_available() -> bool:
    try:
        psycopg.connect("postgresql://mcpbridge:mcpbridge@127.0.0.1:5432/mcpbridge",
                        connect_timeout=2).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.mark.skipif(not _postgres_available(), reason="Postgres not running")
def test_local_token_store_encrypts_at_rest():
    store = LocalTokenStore("test-enc-key")
    tokens = TokenSet(access_token="secret-access", refresh_token="secret-refresh",
                      expires_at=123.0)
    store.put("pg-user", "pg-svc", tokens)
    assert store.get("pg-user", "pg-svc") == tokens
    with store._connect() as conn:
        blob = conn.execute("SELECT ciphertext FROM user_tokens WHERE user_id = 'pg-user'"
                            ).fetchone()[0]
    assert b"secret-access" not in bytes(blob)
    assert LocalTokenStore("another-key").get("pg-user", "pg-svc") is None
    store.delete("pg-user", "pg-svc")
    assert store.get("pg-user", "pg-svc") is None
