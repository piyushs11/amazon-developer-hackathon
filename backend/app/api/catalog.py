"""Service lookups for the UI: resolve a URL or name (S1), and one service's public details.

REGISTRY=postgres -> Dev 1's resolver and registry (seeded from the catalog)
REGISTRY=memory   -> the contract fixtures (contracts/fixtures/spec.*.json + mapped.*.json), so
                     `make dev` works without Postgres
"""
import json
from functools import cache
from pathlib import Path

from backend.app.api.schemas import ServiceDetails, ServiceTool
from backend.app.auth.settings import get_settings
from backend.app.resolver import (
    NameLocation,
    ResolvedService,
    ResolveResponse,
    ServiceResolverInput,
    resolve,
)
from backend.app.resolver.resolver import _domains

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


@cache
def _fixture(kind: str) -> dict[str, dict]:
    out = {}
    for path in sorted(FIXTURES.glob(f"{kind}.*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("service_uuid"):
            out[data["service_uuid"]] = data
    return out


def _summary(spec: dict) -> ResolvedService:
    return ResolvedService(service_uuid=spec["service_uuid"], service_name=spec["service_name"],
                           domain=spec["domain"])


def _resolve_fixture(query: ServiceResolverInput) -> ResolveResponse:
    specs = list(_fixture("spec").values())
    if query.input_type == "url":
        for domain in _domains(query.webpage_url):
            hit = next((s for s in specs if s["domain"] == domain), None)
            if hit:
                return ResolveResponse(status="resolved", service=_summary(hit))
        return ResolveResponse(status="not_found")
    name = query.name_location.name.strip().lower()
    hits = [s for s in specs if name and name in s["service_name"].lower()]
    if len(hits) == 1:
        return ResolveResponse(status="resolved", service=_summary(hits[0]))
    if hits:
        return ResolveResponse(status="ambiguous", candidates=[_summary(s) for s in hits])
    return ResolveResponse(status="not_found")


def resolve_service(query: ServiceResolverInput) -> ResolveResponse:
    """Blocking (Postgres): call from a thread."""
    if get_settings().registry == "postgres":
        return resolve(query)
    return _resolve_fixture(query)


def guess_input(text: str) -> ServiceResolverInput:
    """What the user typed: a URL/domain if it has a dot or slash, otherwise a name."""
    text = text.strip()
    if "." in text or "/" in text:
        return ServiceResolverInput(input_type="url", webpage_url=text)
    return ServiceResolverInput(input_type="name_location", name_location=NameLocation(name=text))


def _tools(endpoints: list[dict]) -> list[ServiceTool]:
    return [ServiceTool(name=e["tool_name"], description=e["description"],
                        read_only=bool(e["read_only"])) for e in endpoints]


def service_details(service_uuid: str) -> ServiceDetails | None:
    """Public details of one service (no user data). Blocking: call from a thread."""
    from backend.app.deploy import mcp_url
    from backend.app.gateway.bundles import get_registry

    if get_settings().registry == "postgres":
        from backend.app.db import registry

        row = registry.get_service(service_uuid)
        if row is None:
            return None
        name, domain = row.service_name, row.domain
        tools = _tools([e.model_dump() for e in registry.get_endpoints(service_uuid)])
    else:
        spec = _fixture("spec").get(service_uuid)
        if spec is None:
            return None
        name, domain = spec["service_name"], spec["domain"]
        tools = _tools(_fixture("mapped").get(service_uuid, {}).get("endpoints", []))
    active = get_registry().get_active_bundle(service_uuid)
    return ServiceDetails(
        service_uuid=service_uuid, service_name=name, domain=domain, tools=tools,
        published=active is not None, version=active.version if active else None,
        mcp_url=mcp_url(service_uuid) if active else None,
    )
