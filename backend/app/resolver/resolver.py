"""Step 0: turn the user's URL or name + city into a registered service."""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, model_validator

from backend.app.db import registry
from backend.app.db.registry import ServiceRow


class NameLocation(BaseModel):
    name: str
    city: str | None = None  # accepted but unused: C1 has no city field yet


class ServiceResolverInput(BaseModel):
    input_type: Literal["url", "name_location"]
    webpage_url: str | None = None
    name_location: NameLocation | None = None

    @model_validator(mode="after")
    def _matching_field_is_set(self):
        if self.input_type == "url" and not self.webpage_url:
            raise ValueError("webpage_url is required when input_type is 'url'")
        if self.input_type == "name_location" and not self.name_location:
            raise ValueError("name_location is required when input_type is 'name_location'")
        return self


class ResolvedService(BaseModel):
    service_uuid: str
    service_name: str
    domain: str


class ResolveResponse(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found"]
    service: ResolvedService | None = None  # set when resolved
    candidates: list[ResolvedService] | None = None  # set when ambiguous


def _summary(row: ServiceRow) -> ResolvedService:
    return ResolvedService(
        service_uuid=row.service_uuid, service_name=row.service_name, domain=row.domain
    )


def _domains(url: str) -> list[str]:
    # "https://www.shop.demobistro.test/menu"
    #   -> ["www.shop.demobistro.test", "shop.demobistro.test", "demobistro.test"]
    url = url.strip()
    if "//" not in url:
        url = "//" + url  # accept "demobistro.test/menu" without a scheme
    host = (urlsplit(url).hostname or "").rstrip(".")  # hostname is lowercase, no port
    if not host:
        return []
    labels = host.split(".")
    return [".".join(labels[i:]) for i in range(max(len(labels) - 1, 1))]


def _resolve_url(url: str) -> ResolveResponse:
    # Most specific first, so a registered subdomain wins over its parent.
    for domain in _domains(url):
        row = registry.find_by_domain(domain)
        if row:
            return ResolveResponse(status="resolved", service=_summary(row))
    return ResolveResponse(status="not_found")


def _resolve_name(query: NameLocation) -> ResolveResponse:
    name = query.name.strip().lower()
    if not name:
        return ResolveResponse(status="not_found")
    rows = registry.search_by_name(name, query.city)
    # Rank: exact name, then prefix, then contains (sorted() is stable, keeps name order).
    ranked = sorted(
        rows,
        key=lambda r: (r.service_name.lower() != name, not r.service_name.lower().startswith(name)),
    )
    exact = [r for r in ranked if r.service_name.lower() == name]
    if len(ranked) == 1 or len(exact) == 1:
        return ResolveResponse(status="resolved", service=_summary(ranked[0]))
    if ranked:
        return ResolveResponse(status="ambiguous", candidates=[_summary(r) for r in ranked])
    return ResolveResponse(status="not_found")


def resolve(query: ServiceResolverInput) -> ResolveResponse:
    if query.input_type == "url":
        return _resolve_url(query.webpage_url)
    return _resolve_name(query.name_location)
