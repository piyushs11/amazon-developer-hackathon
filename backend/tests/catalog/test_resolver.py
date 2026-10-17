"""Tests for Step 0: resolve (backend/app/resolver). The registry is faked, so no Postgres needed."""
import pytest
from pydantic import ValidationError

from backend.app.db import registry
from backend.app.db.registry import ServiceRow
from backend.app.resolver import ServiceResolverInput, resolve

BISTRO = "11111111-1111-1111-1111-111111111111"
EXPRESS = "55555555-5555-5555-5555-555555555555"
BAR = "66666666-6666-6666-6666-666666666666"
HOSTILE = "33333333-3333-3333-3333-333333333333"

ROWS = [
    ServiceRow(service_uuid=uuid, service_name=name, domain=domain,
               base_url=f"http://{domain}", auth_type="oauth2")
    for uuid, name, domain in [
        (BISTRO, "Demo Bistro", "demobistro.test"),
        (EXPRESS, "Demo Bistro Express", "express.demobistro.test"),
        (BAR, "Bistro Bar", "bistrobar.test"),
        (HOSTILE, "Hostile Service", "hostile.test"),
    ]
]


@pytest.fixture(autouse=True)
def fake_registry(monkeypatch):
    # Same behaviour as the SQL: exact domain match; ILIKE %name% ordered by name.
    monkeypatch.setattr(
        registry, "find_by_domain", lambda d: next((r for r in ROWS if r.domain == d), None)
    )
    monkeypatch.setattr(
        registry, "search_by_name",
        lambda name, city: sorted(
            (r for r in ROWS if name.lower() in r.service_name.lower()),
            key=lambda r: r.service_name,
        ),
    )


def _url(url: str):
    return resolve(ServiceResolverInput(input_type="url", webpage_url=url))


def _name(name: str):
    return resolve(ServiceResolverInput(input_type="name_location", name_location={"name": name}))


@pytest.mark.parametrize(
    "url", ["https://demobistro.test", "https://www.demobistro.test/menu", "DemoBistro.test:8080"]
)
def test_url_resolved(url):
    result = _url(url)
    assert result.status == "resolved"
    assert result.service.service_uuid == BISTRO


def test_url_registered_subdomain_wins_over_parent():
    assert _url("https://express.demobistro.test/order").service.service_uuid == EXPRESS


@pytest.mark.parametrize("url", ["https://unknown.test", "https://", "not a url"])
def test_url_not_found(url):
    result = _url(url)
    assert (result.status, result.service, result.candidates) == ("not_found", None, None)


def test_name_single_exact_match_resolved():
    # "Demo Bistro Express" also matches, but only one name matches exactly.
    assert _name("demo bistro").service.service_uuid == BISTRO


def test_name_single_match_resolved():
    assert _name("hostile").service.service_uuid == HOSTILE


def test_name_ambiguous_is_ranked():
    result = _name("bistro")
    assert result.status == "ambiguous"
    # Prefix match first, then contains matches in name order.
    assert [c.service_uuid for c in result.candidates] == [BAR, BISTRO, EXPRESS]


@pytest.mark.parametrize("name", ["pizzeria", "   "])
def test_name_not_found(name):
    assert _name(name).status == "not_found"


@pytest.mark.parametrize(
    "raw", [{"input_type": "url"}, {"input_type": "name_location"}, {"input_type": "phone"}]
)
def test_input_missing_matching_field_is_rejected(raw):
    with pytest.raises(ValidationError):
        ServiceResolverInput.model_validate(raw)
