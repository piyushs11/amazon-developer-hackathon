"""Catalog text must never become executable code in a generated tool."""
import ast
import json
from pathlib import Path

import pytest
from jinja2 import Template

from backend.app.codegen.sanitizer import SanitizeError, safe_text, sanitize_mapped
from backend.app.codegen.templates.service_template import ENDPOINT_TEMPLATE
from backend.app.mapper import map_service
from backend.app.spec import parse_spec

ROOT = Path(__file__).resolve().parents[3]
INJECTION = 'hi"""\n    import os; os.system("echo PWNED")\n    """'


def _endpoint(**overrides) -> dict:
    endpoint = {
        "endpoint_id": "get_thing", "tool_name": "get_thing", "method": "GET",
        "description": "Get a thing.", "path_template": "/things/{thing_id}", "read_only": True,
        "params": [{"name": "thing_id", "python_type": "str", "json_type": "string",
                    "required": True, "location": "path", "description": "Thing ID"}],
        "input_schema": {},
    }
    endpoint.update(overrides)
    return endpoint


def _service(*endpoints) -> dict:
    return {"service_uuid": "u-1", "service_name": "Evil Co", "endpoints": list(endpoints)}


def _render(endpoint: dict) -> str:
    return Template(ENDPOINT_TEMPLATE).render(service_name="evil_co", base_url="", **endpoint)


def _calls(source: str) -> set[str]:
    return {ast.unparse(n.func) for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)}


def test_docstring_breakout_stays_text():
    raw = _endpoint(description=INJECTION)
    assert "os.system" in _calls(_render(raw))  # proves the unsanitised template is exploitable

    safe = sanitize_mapped(_service(raw))["endpoints"][0]
    source = _render(safe)
    assert "os.system" not in _calls(source)
    assert '"""' not in safe["description"] and "\n" not in safe["description"]


def test_param_description_cannot_forge_lines():
    params = [{**_endpoint()["params"][0], "description": 'x\n    other: forged"""'}]
    safe = sanitize_mapped(_service(_endpoint(params=params)))["endpoints"][0]
    ast.parse(_render(safe))
    assert safe["params"][0]["description"] == "x other: forged'''"


@pytest.mark.parametrize("path", ["/things/{0}", "/things/{thing_id.__class__}", "/things/{}",
                                  '/things/{thing_id}"+x+"', "things/{thing_id}", "/a/{other}"])
def test_unsafe_paths_rejected(path):
    with pytest.raises(SanitizeError):
        sanitize_mapped(_service(_endpoint(path_template=path)))


@pytest.mark.parametrize("field,value", [
    ("tool_name", "import os"), ("tool_name", "class"), ("method", "GET\nimport os"),
])
def test_unsafe_endpoint_fields_rejected(field, value):
    with pytest.raises(SanitizeError):
        sanitize_mapped(_service(_endpoint(**{field: value})))


@pytest.mark.parametrize("key,value", [
    ("name", "x; import os"), ("python_type", "__import__('os')"), ("location", "cookie"),
    ("wire_name", 'a"+b'),
])
def test_unsafe_params_rejected(key, value):
    params = [{**_endpoint()["params"][0], key: value}]
    with pytest.raises(SanitizeError):
        sanitize_mapped(_service(_endpoint(params=params)))


def test_hostile_catalog_spec_renders_safely():
    raw = json.loads((ROOT / "mock-services/catalog/specs/hostile.json").read_text(encoding="utf-8"))
    mapped = map_service(parse_spec(raw)).model_dump(exclude_none=True)
    for endpoint in sanitize_mapped(mapped)["endpoints"]:
        source = _render(endpoint)
        tree = ast.parse(source)  # used to be a SyntaxError (and could be valid code)
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert imports <= {"json", "httpx"}


def test_wire_name_is_sent_upstream():
    params = [
        {"name": "order_id", "wire_name": "order-id", "python_type": "str", "json_type": "string",
         "required": True, "location": "query", "description": "Order"},
        {"name": "class_", "wire_name": "class", "python_type": "str", "json_type": "string",
         "required": False, "location": "body", "description": "Class"},
    ]
    endpoint = sanitize_mapped(_service(_endpoint(path_template="/items", params=params)))["endpoints"][0]
    source = _render(endpoint)
    assert '"order-id": order_id' in source and '"class": class_' in source
    ast.parse(source)


def test_demo_bistro_unchanged():
    mapped = json.loads((ROOT / "contracts/fixtures/mapped.demo_bistro.json").read_text(encoding="utf-8"))
    assert sanitize_mapped(mapped)["endpoints"][0]["description"] == mapped["endpoints"][0]["description"]


def test_safe_text():
    assert safe_text('a\\b "c"\r\n\td') == "a/b 'c' d"
    assert safe_text(None, "fallback") == "fallback"

