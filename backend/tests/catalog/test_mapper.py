"""Tests for Step 2: map_service (backend/app/mapper)."""
import json
import keyword
import re
from pathlib import Path

import pytest

from backend.app.mapper import MapError, map_service
from backend.app.spec import parse_spec

ROOT = Path(__file__).parents[3]
SPECS_DIR = ROOT / "mock-services" / "catalog" / "specs"
C2_FIXTURE = ROOT / "contracts" / "fixtures" / "mapped.demo_bistro.json"

# The identifier rule Dev 2's sanitizer re-checks.
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def bistro() -> dict:
    # Fresh copy per test, so tests can change it freely.
    return _load(SPECS_DIR / "demo_bistro.json")


@pytest.fixture
def hostile_endpoint():
    return map_service(parse_spec(_load(SPECS_DIR / "hostile.json"))).endpoints[0]


def _param(name: str, **overrides) -> dict:
    return {"name": name, "type": "string", "required": True, "location": "query", **overrides}


def test_golden_demo_bistro(bistro):
    mapped = map_service(parse_spec(bistro))
    assert mapped.model_dump(exclude_none=True) == _load(C2_FIXTURE)


def test_hostile_names_are_safe_identifiers(hostile_endpoint):
    names = [hostile_endpoint.tool_name] + [p.name for p in hostile_endpoint.params]
    for name in names:
        assert IDENTIFIER.match(name) and not keyword.iskeyword(name)


def test_hostile_names_keep_wire_name(hostile_endpoint):
    assert [(p.name, p.wire_name) for p in hostile_endpoint.params] == [
        ("order_id", "order-id"),
        ("class_", "class"),
        ("_2fast", "2fast"),
    ]


def test_hostile_path_uses_sanitised_name(hostile_endpoint):
    assert hostile_endpoint.path_template == "/items/{order_id}"


def test_unknown_type_becomes_str_with_warning(caplog):
    endpoint = map_service(parse_spec(_load(SPECS_DIR / "hostile.json"))).endpoints[0]
    param = endpoint.params[1]
    assert (param.json_type, param.python_type) == ("string", "str")
    assert "unknown type 'uuid'" in caplog.text


def test_missing_description_gets_readable_fallback(hostile_endpoint):
    assert hostile_endpoint.params[2].description == "2fast"
    assert hostile_endpoint.input_schema["properties"]["_2fast"]["description"] == "2fast"


def test_required_params_come_first(bistro):
    bistro["endpoints"][0]["params"] = [
        _param("limit", required=False),
        _param("query"),
        _param("page", required=False),
        _param("city"),
    ]
    endpoint = map_service(parse_spec(bistro)).endpoints[0]
    assert [p.name for p in endpoint.params] == ["query", "city", "limit", "page"]
    assert endpoint.input_schema["required"] == ["query", "city"]


def test_colon_path_is_normalised(bistro):
    bistro["endpoints"][1]["path"] = "/orders/:order_id"
    assert map_service(parse_spec(bistro)).endpoints[1].path_template == "/orders/{order_id}"


def test_type_mapping(bistro):
    types = ["string", "integer", "number", "boolean", "array", "object"]
    bistro["endpoints"][0]["params"] = [_param(f"p{i}", type=t) for i, t in enumerate(types)]
    params = map_service(parse_spec(bistro)).endpoints[0].params
    assert [p.python_type for p in params] == ["str", "int", "float", "bool", "list", "dict"]


def test_param_name_collision_is_rejected(bistro):
    bistro["endpoints"][0]["params"] = [_param("order-id"), _param("order_id")]
    with pytest.raises(MapError) as exc:
        map_service(parse_spec(bistro))
    assert exc.value.code == "MAP_NAME_COLLISION"


def test_tool_name_collision_is_rejected(bistro):
    bistro["endpoints"][0]["id"] = "get-order"
    bistro["endpoints"][1]["id"] = "get_order"
    with pytest.raises(MapError) as exc:
        map_service(parse_spec(bistro))
    assert exc.value.code == "MAP_NAME_COLLISION"
