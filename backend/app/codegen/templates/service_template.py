'''Jinja2 template for ONE endpoint of a service (fields follow MappedService, C2).
Rendered into endpoints/<tool_name>.py; the service main file imports the tool function.

Placeholders:
    service_name   identifier-safe service name, e.g. "demo_bistro"
    base_url       unused: the service base URL is NOT baked into the code; the tool reads it
                   at call time with get_current_base_url() (set by the gateway from the registry)
    endpoint_id    e.g. "get_order_status"; names the HTTP helper
    tool_name      e.g. "get_order_status"; MCP tool is {tool_name}for{service_name}
    method         HTTP method: GET, POST, PUT, PATCH, DELETE
    description    endpoint description -> tool docstring
    path_template  e.g. "/orders/{order_id}"
    read_only      True / False (used by the main file for readOnlyHint)
    params         list of {name, wire_name?, python_type, json_type, required, location, description}
                   query/body/header keys use wire_name (the API's own name) when it is set
                   location is one of: path, query, body, header
    input_schema   {properties, required}; descriptions are already carried by params
'''

ENDPOINT_TEMPLATE = '''import json

import httpx
from runtime.auth_context import get_current_base_url, get_current_token


async def {{ endpoint_id }}_request(token: str, url: str, end_point: str, method: str, params: dict, body: dict, headers: dict):
    """Call `{{ endpoint_id }}` on {{ service_name }}.

    Sends a `{{ method }}` request to `{url}{end_point}` with the given bearer token.

    Args:
        token: Access token, sent as "Authorization: Bearer {token}".
        url: Base API URL of the service.
        end_point: Path appended directly to `url`, path params already filled in.
        method: HTTP method.
        params: Query parameters dict.
        body: JSON body dict, sent only when non-empty.
        headers: Extra request headers.

    Returns:
        dict: The parsed JSON response body on success.
        int: The HTTP status code if the request fails (non-2xx response).
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method,
                f"{url}{end_point}",
                headers={**headers, "Authorization": f"Bearer {token}"},
                params=params,
                json=body or None,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return e.response.status_code


{% set required = params | selectattr("required") | list -%}
{% set optional = params | rejectattr("required") | list -%}
async def {{ tool_name }}for{{ service_name }}(
{%- for p in required %}{{ p.name }}: {{ p.python_type }}{{ ", " if not loop.last or optional }}{% endfor %}
{%- for p in optional %}{{ p.name }}: {{ p.python_type }} | None = None{{ ", " if not loop.last }}{% endfor %}) -> str:
    """{{ description }}
{% if params %}
    Args:
{%- for p in params %}
        {{ p.name }}: {{ p.description }}
{%- endfor %}
{% endif %}
    Returns:
        str: JSON-encoded response, or a JSON-encoded message if the call failed.
    """
    token = get_current_token()  # set by the caller just before this call, never by the LLM
    path_params = {
{%- for p in params if p.location == "path" %}
        "{{ p.name }}": {{ p.name }},
{%- endfor %}
    }
    query = {
{%- for p in params if p.location == "query" %}
        "{{ p.wire_name or p.name }}": {{ p.name }},
{%- endfor %}
    }
    body = {
{%- for p in params if p.location == "body" %}
        "{{ p.wire_name or p.name }}": {{ p.name }},
{%- endfor %}
    }
    headers = {
{%- for p in params if p.location == "header" %}
        "{{ p.wire_name or p.name }}": {{ p.name }},
{%- endfor %}
    }
    query = {k: v for k, v in query.items() if v is not None}
    body = {k: v for k, v in body.items() if v is not None}
    headers = {k: str(v) for k, v in headers.items() if v is not None}

    result = await {{ endpoint_id }}_request(
        token,
        get_current_base_url(),  # set by the caller from the registry, never baked into the code
        "{{ path_template }}".format(**path_params),
        "{{ method }}",
        query,
        body,
        headers,
    )

    if not result or isinstance(result, int):
        return json.dumps({"message": "request to {{ tool_name }} failed", "status": result})

    return json.dumps(result)
'''
