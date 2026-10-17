"""Which bundle version is active for a service (seam S13).

Same function names as Dev 1's registry (backend.app.db.registry):
    get_active_bundle(service_uuid) -> ActiveBundle | None
    set_active_version(service_uuid, version, bundle_path, spec_hash) -> None

REGISTRY=memory   -> in-memory, pre-seeded with the hand-written Demo Bistro bundle
REGISTRY=postgres -> Dev 1's Postgres registry (after feat/dev1 is merged)
"""
import threading
import time
from pathlib import Path

from pydantic import BaseModel

from backend.app.auth.services import DEMO_BISTRO_UUID
from backend.app.auth.settings import get_settings

FIXTURE_BUNDLE = Path(__file__).resolve().parents[3] / "contracts/fixtures/bundle.demo_bistro"
FIXTURE_VERSION = "handwritten-v1"
CACHE_SECONDS = 5.0


class ActiveBundle(BaseModel):  # same fields as Dev 1's ActiveBundle
    version: str
    bundle_path: str
    base_url: str


class InMemoryRegistry:
    def __init__(self):
        self._base_urls: dict[str, str] = {}
        self._active: dict[str, ActiveBundle] = {}
        self._lock = threading.Lock()

    def add_service(self, service_uuid: str, base_url: str) -> None:
        self._base_urls[service_uuid] = base_url

    def get_active_bundle(self, service_uuid: str) -> ActiveBundle | None:
        return self._active.get(service_uuid)

    def set_active_version(
        self, service_uuid: str, version: str, bundle_path: str, spec_hash: str = ""
    ) -> None:
        if service_uuid not in self._base_urls:
            raise LookupError(f"service '{service_uuid}' is not in the registry")
        with self._lock:
            self._active[service_uuid] = ActiveBundle(
                version=version, bundle_path=bundle_path, base_url=self._base_urls[service_uuid]
            )


class PostgresRegistry:
    """Dev 1's repository with a short cache: get_active_bundle runs on every MCP request."""

    def __init__(self):
        self._cache: dict[str, tuple[float, ActiveBundle | None]] = {}

    def get_active_bundle(self, service_uuid: str) -> ActiveBundle | None:
        hit = self._cache.get(service_uuid)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        from backend.app.db.registry import get_active_bundle

        row = get_active_bundle(service_uuid)
        active = ActiveBundle.model_validate(row.model_dump()) if row else None
        self._cache[service_uuid] = (time.monotonic(), active)
        return active

    def set_active_version(
        self, service_uuid: str, version: str, bundle_path: str, spec_hash: str = ""
    ) -> None:
        from backend.app.db.registry import set_active_version

        set_active_version(service_uuid, version, bundle_path, spec_hash)
        self._cache.pop(service_uuid, None)


_registry = None


def get_registry():
    global _registry
    if _registry is None:
        if get_settings().registry == "postgres":
            _registry = PostgresRegistry()
        else:
            from backend.app.auth.factory import get_service_directory

            _registry = InMemoryRegistry()
            demo = get_service_directory().get(DEMO_BISTRO_UUID)
            _registry.add_service(DEMO_BISTRO_UUID, demo.base_url)
            _registry.set_active_version(DEMO_BISTRO_UUID, FIXTURE_VERSION, str(FIXTURE_BUNDLE))
    return _registry


def reset() -> None:
    global _registry
    _registry = None
