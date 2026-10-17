"""Tests for Step 1: parse_spec (backend/app/spec)."""
import json
from pathlib import Path

import pytest

from backend.app.spec import SpecError, parse_spec

ROOT = Path(__file__).parents[3]
SPECS_DIR = ROOT / "mock-services" / "catalog" / "specs"
C1_FIXTURE = ROOT / "contracts" / "fixtures" / "spec.demo_bistro.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def bistro() -> dict:
    # Fresh copy per test, so tests can break it freely.
    return _load(SPECS_DIR / "demo_bistro.json")


def _error_codes(raw) -> list[str]:
    with pytest.raises(SpecError) as exc:
        parse_spec(raw)
    return [err.code for err in exc.value.errors]


def test_demo_bistro_parses(bistro):
    spec = parse_spec(bistro)
    assert [e.id for e in spec.endpoints] == ["search_menu", "get_order_status", "place_order"]


def test_catalog_demo_bistro_matches_c1_fixture(bistro):
    # The catalog copy and the shared fixture must not drift apart.
    assert bistro == _load(C1_FIXTURE)


def test_hostile_parses_with_raw_names():
    # Hostile names are valid spec input; sanitising them is the mapper's job.
    spec = parse_spec(_load(SPECS_DIR / "hostile.json"))
    assert [p.name for p in spec.endpoints[0].params] == ["order-id", "class", "2fast"]


def test_empty_endpoints():
    assert _error_codes(_load(SPECS_DIR / "hostile_empty.json")) == ["SPEC_NO_ENDPOINTS"]


def test_missing_field(bistro):
    del bistro["service_name"]
    assert _error_codes(bistro) == ["SPEC_MISSING_FIELD"]


def test_unsupported_auth_type(bistro):
    bistro["auth_type"] = "apikey"
    assert _error_codes(bistro) == ["SPEC_BAD_AUTH"]


def test_oauth2_without_oauth_block(bistro):
    del bistro["oauth"]
    assert _error_codes(bistro) == ["SPEC_BAD_AUTH"]


def test_bad_method(bistro):
    bistro["endpoints"][0]["method"] = "FETCH"
    assert _error_codes(bistro) == ["SPEC_BAD_METHOD"]


def test_duplicate_endpoint_id(bistro):
    bistro["endpoints"][1]["id"] = bistro["endpoints"][0]["id"]
    assert _error_codes(bistro) == ["SPEC_DUPLICATE_ID"]


def test_bad_param_location(bistro):
    bistro["endpoints"][0]["params"][0]["location"] = "cookie"
    assert _error_codes(bistro) == ["SPEC_BAD_PARAM"]


def test_collects_all_errors(bistro):
    bistro["auth_type"] = "apikey"
    bistro["endpoints"][0]["method"] = "FETCH"
    bistro["endpoints"][1]["id"] = bistro["endpoints"][0]["id"]
    assert _error_codes(bistro) == ["SPEC_BAD_AUTH", "SPEC_BAD_METHOD", "SPEC_DUPLICATE_ID"]


def test_non_dict_input_does_not_crash():
    assert _error_codes([1, 2]) == ["SPEC_MISSING_FIELD"]
