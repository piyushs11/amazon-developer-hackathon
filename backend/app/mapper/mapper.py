"""Step 2: turn a ServiceSpec (C1) into a MappedService (C2)."""
import keyword
import logging
import re

from contracts.models import (
    EndpointSpec,
    MappedEndpoint,
    MappedParam,
    MappedService,
    ParamSpec,
    ServiceSpec,
)

logger = logging.getLogger(__name__)

# JSON type -> Python type
PYTHON_TYPES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}

# A path placeholder: "/:order_id" or "{order_id}"
_PLACEHOLDER = re.compile(r"(?<=/):([^/]+)|\{([^}]+)\}")


class MapError(Exception):
    # codes: MAP_NAME_COLLISION
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _sanitise(name: str) -> str:
    # Lowercase identifier matching ^[a-z_][a-z0-9_]*$, never a Python keyword.
    clean = re.sub(r"[^a-z0-9_]", "_", name.lower())
    if not clean or clean[0].isdigit():
        clean = "_" + clean
    if keyword.iskeyword(clean):
        clean += "_"
    return clean


def _readable(name: str) -> str:
    # Fallback description when the spec gives none: "order-id" -> "Order id".
    return re.sub(r"[_\-]+", " ", name).strip().capitalize()


def _reject_collisions(names: list[str], where: str) -> None:
    clashes = sorted({n for n in names if names.count(n) > 1})
    if clashes:
        raise MapError("MAP_NAME_COLLISION", f"{where}: names collide after sanitising: {clashes}")


def _map_param(param: ParamSpec, endpoint_id: str) -> MappedParam:
    json_type = param.type
    if json_type not in PYTHON_TYPES:
        logger.warning(
            "endpoint '%s': param '%s' has unknown type '%s', using string",
            endpoint_id, param.name, param.type,
        )
        json_type = "string"
    name = _sanitise(param.name)
    return MappedParam(
        name=name,
        # Kept so the runtime can send the original key upstream.
        wire_name=param.name if name != param.name else None,
        python_type=PYTHON_TYPES[json_type],
        json_type=json_type,
        required=param.required,
        location=param.location,
        description=param.description or _readable(param.name),
    )


def _map_endpoint(endpoint: EndpointSpec) -> MappedEndpoint:
    params = [_map_param(p, endpoint.id) for p in endpoint.params]
    _reject_collisions([p.name for p in params], f"endpoint '{endpoint.id}'")
    # Stable sort: required first, spec order otherwise.
    params.sort(key=lambda p: not p.required)
    return MappedEndpoint(
        endpoint_id=endpoint.id,
        tool_name=_sanitise(endpoint.id),
        method=endpoint.method,
        description=endpoint.description,
        # Both placeholder styles become "{name}", using the sanitised param name.
        path_template=_PLACEHOLDER.sub(
            lambda m: "{" + _sanitise(m.group(1) or m.group(2)) + "}", endpoint.path
        ),
        read_only=endpoint.method == "GET",
        params=params,
        input_schema={
            "type": "object",
            "properties": {
                p.name: {"type": p.json_type, "description": p.description} for p in params
            },
            "required": [p.name for p in params if p.required],
        },
    )


def map_service(spec: ServiceSpec) -> MappedService:
    endpoints = [_map_endpoint(e) for e in spec.endpoints]
    _reject_collisions([e.tool_name for e in endpoints], f"service '{spec.service_uuid}'")
    return MappedService(
        service_uuid=spec.service_uuid,
        service_name=spec.service_name,
        endpoints=endpoints,
    )
