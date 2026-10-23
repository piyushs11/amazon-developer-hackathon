"""Service lookups for the UI: resolve a URL or name (S1), and one service's public details.

REGISTRY=postgres -> Dev 1's resolver and registry (seeded from the catalog)
REGISTRY=memory   -> the contract fixtures (contracts/fixtures/spec.*.json + mapped.*.json), so
                     `make dev` works without Postgres
"""
import json
import re
from functools import cache
from pathlib import Path

from backend.app.api.schemas import ServiceDetails, ServiceSummary, ServiceTool
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


_NAME_IN_CITY = re.compile(r"^(?P<name>.+?)(?:\s+in\s+|\s*,\s*)(?P<city>[A-Za-z][A-Za-z .'-]*)$", re.IGNORECASE)


def guess_input(text: str) -> ServiceResolverInput:
    """What the user typed: a URL/domain if it has a dot or slash, otherwise a name, optionally
    with a city ("Lakeside in Chicago", "Lakeside, Evanston")."""
    text = text.strip()
    if "." in text or "/" in text:
        return ServiceResolverInput(input_type="url", webpage_url=text)
    m = _NAME_IN_CITY.match(text)
    if m:
        where = NameLocation(name=m["name"].strip(), city=m["city"].strip())
    else:
        where = NameLocation(name=text)
    return ServiceResolverInput(input_type="name_location", name_location=where)


def _tools(endpoints: list[dict]) -> list[ServiceTool]:
    return [ServiceTool(name=e["tool_name"], description=e["description"],
                        read_only=bool(e["read_only"])) for e in endpoints]


def _connected_users(service_uuid: str) -> int:
    from backend.app.auth.factory import get_mapping

    try:
        return get_mapping().count_for_service(service_uuid)
    except Exception:  # noqa: BLE001 - a count is decoration; never fail the page for it
        return 0


def service_details(service_uuid: str) -> ServiceDetails | None:
    """Public details of one service (no user data). Blocking: call from a thread."""
    from backend.app.deploy import mcp_url
    from backend.app.gateway.bundles import get_registry

    published_at = None
    if get_settings().registry == "postgres":
        from backend.app.db import registry

        row = registry.get_service(service_uuid)
        if row is None:
            return None
        name, domain, profile = row.service_name, row.domain, row.profile or {}
        scopes = row.oauth.scopes if row.oauth else []
        published_at = row.published_at
        tools = _tools([e.model_dump() for e in registry.get_endpoints(service_uuid)])
    else:
        spec = _fixture("spec").get(service_uuid)
        if spec is None:
            return None
        name, domain, profile = spec["service_name"], spec["domain"], spec.get("profile") or {}
        scopes = (spec.get("oauth") or {}).get("scopes", [])
        tools = _tools(_fixture("mapped").get(service_uuid, {}).get("endpoints", []))
    registry_ = get_registry()
    active = registry_.get_active_bundle(service_uuid)
    stale = getattr(registry_, "spec_changed", None)
    return ServiceDetails(
        service_uuid=service_uuid, service_name=name, domain=domain, tools=tools,
        published=active is not None, version=active.version if active else None,
        mcp_url=mcp_url(service_uuid) if active else None,
        profile=profile, scopes=scopes, published_at=published_at if active else None,
        connected_users=_connected_users(service_uuid),
        update_available=bool(active and stale and stale(service_uuid)),
    )


def list_catalog() -> list[ServiceSummary]:
    """Every listed service (the ones with a profile). Blocking: call from a thread."""
    if get_settings().registry == "postgres":
        from backend.app.db import registry

        return [ServiceSummary(service_uuid=r.service_uuid, service_name=r.service_name, domain=r.domain,
                               published=r.active_version is not None, profile=r.profile or {})
                for r in registry.list_services()]
    from backend.app.gateway.bundles import get_registry

    return [ServiceSummary(service_uuid=u, service_name=s["service_name"], domain=s["domain"],
                           published=get_registry().get_active_bundle(u) is not None,
                           profile=s.get("profile") or {})
            for u, s in _fixture("spec").items() if s.get("profile")]
