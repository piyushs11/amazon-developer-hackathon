"""Make a mapped service (C2) safe to render into Python source. Fails closed.

Catalog text is untrusted and ends up inside generated code that runs in the shared gateway
process, so every value the endpoint template interpolates is checked or neutralised here:

    identifiers   tool / endpoint / param names must match ^[a-z_][a-z0-9_]*$ and not be keywords
    method        one of GET POST PUT PATCH DELETE
    python_type   one of str int float bool list dict
    location      one of path query body header
    path_template only [A-Za-z0-9_-/{}.~]; every {placeholder} is a path param of the endpoint
    wire_name     only [A-Za-z0-9_.-[]] (it becomes a dict key string)
    descriptions  single line, no quotes or backslashes (they become docstrings)

Raises SanitizeError for anything that cannot be made safe; never returns unsafe data.
"""
import keyword
import re

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_PATH = re.compile(r"^/[A-Za-z0-9_\-/{}.~]*$")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_WIRE = re.compile(r"^[A-Za-z0-9_.\-\[\]]{1,128}$")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
PYTHON_TYPES = {"str", "int", "float", "bool", "list", "dict"}
LOCATIONS = {"path", "query", "body", "header"}
MAX_DESCRIPTION = 500


class SanitizeError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _identifier(value, where: str) -> str:
    if not isinstance(value, str) or not _IDENT.match(value) or keyword.iskeyword(value):
        raise SanitizeError("INVALID_IDENTIFIER", f"{where}: {value!r} is not a safe identifier")
    return value


def safe_text(value, fallback: str = "") -> str:
    """One printable line with no quotes or backslashes: safe inside a docstring or a string."""
    text = str(value if value is not None else fallback)
    text = text.replace("\\", "/").replace('"', "'")
    text = re.sub(r"[^\x20-\x7E]+", " ", text)  # newlines, tabs, control and non-ASCII chars
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_DESCRIPTION] or fallback


def _path(template, path_params: set[str], where: str) -> str:
    if not isinstance(template, str) or not _PATH.match(template):
        raise SanitizeError("INVALID_PATH", f"{where}: path {template!r} has unsafe characters")
    if template.count("{") != template.count("}"):
        raise SanitizeError("INVALID_PATH", f"{where}: unbalanced braces in {template!r}")
    found = _PLACEHOLDER.findall(template)
    for name in found:
        if name not in path_params:  # also blocks "{0}", "{x.__class__}" and "{}" format tricks
            raise SanitizeError("INVALID_PATH", f"{where}: {{{name}}} is not a path parameter")
    missing = path_params - set(found)
    if missing:
        raise SanitizeError("INVALID_PATH", f"{where}: path parameters {sorted(missing)} not in the path")
    return template


def sanitize_mapped(mapped: dict) -> dict:
    """Return a copy of the mapped service that is safe to render. Raises SanitizeError."""
    endpoints = mapped.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise SanitizeError("NO_ENDPOINTS", "the mapped service has no endpoints")
    out_endpoints = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise SanitizeError("INVALID_ENDPOINT", "an endpoint is not an object")
        tool_name = _identifier(endpoint.get("tool_name") or endpoint.get("endpoint_id"), "tool_name")
        endpoint_id = endpoint.get("endpoint_id") or tool_name
        if not (isinstance(endpoint_id, str) and _IDENT.match(endpoint_id)):
            endpoint_id = tool_name  # endpoint_id names a helper function; fall back to the tool name
        where = f"endpoint {tool_name}"
        method = str(endpoint.get("method", "")).upper()
        if method not in METHODS:
            raise SanitizeError("INVALID_METHOD", f"{where}: method {endpoint.get('method')!r}")

        params, seen = [], set()
        for p in endpoint.get("params") or []:
            name = _identifier(p.get("name"), f"{where} param")
            if name in seen:
                raise SanitizeError("DUPLICATE_PARAM", f"{where}: param {name!r} appears twice")
            seen.add(name)
            if p.get("python_type") not in PYTHON_TYPES:
                raise SanitizeError("INVALID_TYPE", f"{where}: param {name} type {p.get('python_type')!r}")
            if p.get("location") not in LOCATIONS:
                raise SanitizeError("INVALID_LOCATION", f"{where}: param {name} location {p.get('location')!r}")
            wire = p.get("wire_name")
            if wire is not None and not (isinstance(wire, str) and _WIRE.match(wire)):
                raise SanitizeError("INVALID_WIRE_NAME", f"{where}: param {name} wire name {wire!r}")
            params.append({**p, "name": name, "wire_name": wire,
                           "required": bool(p.get("required")),
                           "description": safe_text(p.get("description"), name)})

        path_params = {p["name"] for p in params if p["location"] == "path"}
        out_endpoints.append({
            **endpoint,
            "endpoint_id": endpoint_id,
            "tool_name": tool_name,
            "method": method,
            "description": safe_text(endpoint.get("description"), tool_name),
            "path_template": _path(endpoint.get("path_template"), path_params, where),
            "read_only": bool(endpoint.get("read_only")),
            "params": params,
        })
    return {**mapped, "service_name": safe_text(mapped.get("service_name")),
            "endpoints": out_endpoints}
