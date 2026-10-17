"""Where OAuth reads a service's name and OAuth config from.

REGISTRY=memory   -> the Demo Bistro spec fixture (works before Dev 1's registry is merged)
REGISTRY=postgres -> Dev 1's registry: backend.app.db.registry.get_service()
"""
import json
from pathlib import Path

from pydantic import BaseModel

DEMO_BISTRO_UUID = "11111111-1111-1111-1111-111111111111"
_SPEC_FIXTURE = Path(__file__).resolve().parents[3] / "contracts/fixtures/spec.demo_bistro.json"


class OAuthInfo(BaseModel):
    auth_url: str
    token_url: str
    scopes: list[str] = []


class ServiceInfo(BaseModel):
    service_uuid: str
    service_name: str
    base_url: str
    oauth: OAuthInfo | None = None


# Used when the spec fixture is still the empty Day 0 placeholder.
_DEMO_BISTRO = ServiceInfo(
    service_uuid=DEMO_BISTRO_UUID,
    service_name="Demo Bistro",
    base_url="http://localhost:9000",
    oauth=OAuthInfo(
        auth_url="http://localhost:9100/authorize",
        token_url="http://localhost:9100/token",
        scopes=["read", "order"],
    ),
)


class FixtureServiceDirectory:
    def __init__(self):
        self._services: dict[str, ServiceInfo] = {}
        raw = json.loads(_SPEC_FIXTURE.read_text()) if _SPEC_FIXTURE.exists() else {}
        info = ServiceInfo.model_validate(raw) if raw.get("service_uuid") else _DEMO_BISTRO
        self.add(info)

    def add(self, info: ServiceInfo) -> None:
        self._services[info.service_uuid] = info

    def get(self, service_uuid: str) -> ServiceInfo | None:
        return self._services.get(service_uuid)


class RegistryServiceDirectory:
    def get(self, service_uuid: str) -> ServiceInfo | None:
        from backend.app.db.registry import get_service  # Dev 1, merged separately

        row = get_service(service_uuid)
        if row is None:
            return None
        oauth = OAuthInfo.model_validate(row.oauth.model_dump()) if row.oauth else None
        return ServiceInfo(
            service_uuid=row.service_uuid, service_name=row.service_name,
            base_url=row.base_url, oauth=oauth,
        )
