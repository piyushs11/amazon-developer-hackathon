"""Dev 3 factories: pick fake or real implementations from the environment.

backend/app/core/wiring.py (Dev 4) re-exports these; configure() runs once at startup.

TOKEN_PROVIDER=fake   -> every upstream call uses "demo-token"; tokens/mapping in memory
TOKEN_PROVIDER=memory -> real OAuth tokens + refresh, kept in memory (no Postgres needed)
TOKEN_PROVIDER=local  -> real OAuth tokens + refresh, encrypted in Postgres; mapping in Postgres
"""
from backend.app.auth.identity import DEMO_USER_ID, build_identity
from backend.app.auth.services import (
    DEMO_BISTRO_UUID,
    FixtureServiceDirectory,
    RegistryServiceDirectory,
)
from backend.app.auth.settings import get_settings
from backend.app.auth.vault import InMemoryTokenStore, LocalTokenStore
from backend.app.db.mapping import InMemoryMappingStore, PostgresMappingStore
from runtime import tokens as runtime_tokens

_instances: dict[str, object] = {}


def _once(name: str, build):
    if name not in _instances:
        _instances[name] = build()
    return _instances[name]


def reset() -> None:
    """Tests: forget every instance so the next call re-reads the environment."""
    _instances.clear()
    runtime_tokens.set_token_provider(None)


def get_identity():
    return _once("identity", build_identity)


def get_token_store():
    def build():
        s = get_settings()
        if s.token_provider == "local":
            return LocalTokenStore(s.token_enc_key)
        return InMemoryTokenStore()

    return _once("token_store", build)


def get_mapping():
    def build():
        if get_settings().token_provider == "local":
            return PostgresMappingStore()
        store = InMemoryMappingStore()
        if get_settings().token_provider == "fake":
            # The fixed demo user is "connected" to Demo Bistro out of the box.
            store.upsert_connection(DEMO_USER_ID, DEMO_BISTRO_UUID, "active")
        return store

    return _once("mapping", build)


def get_service_directory():
    def build():
        if get_settings().registry == "postgres":
            return RegistryServiceDirectory()
        return FixtureServiceDirectory()

    return _once("services", build)


def get_token_provider():
    def build():
        from backend.app.auth.oauth import refresh

        kind = get_settings().token_provider
        if kind == "fake":
            return runtime_tokens.FakeTokenProvider()
        if kind in ("memory", "local"):
            return runtime_tokens.StoreTokenProvider(get_token_store(), refresh)
        raise RuntimeError(f"unknown TOKEN_PROVIDER={kind!r}")

    return _once("token_provider", build)


def configure() -> None:
    """Startup hook: make runtime/client.py use this process's token provider."""
    import logging

    from runtime import loader

    app_log = logging.getLogger("mcp_bridge")  # gateway/deploy logs (never tokens)
    if not app_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        app_log.addHandler(handler)
        app_log.setLevel(logging.INFO)
    runtime_tokens.set_token_provider(get_token_provider())
    if get_settings().mode == "aws":  # s3:// bundle paths are read through Dev 2's S3Storage
        from backend.app.storage.add_n_read_mcp_tool import get_storage

        loader.set_reader(get_storage())
