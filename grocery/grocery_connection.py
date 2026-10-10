from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
import yaml
import os
import json


with open("setup.yaml",'r') as f:
    data = yaml.safe_load(f)

# Initialize FastMCP server
mcp = FastMCP("ralphs_grocery")



store_api=data['api']['ralph_store']
auth_endpoint=data['endpoint']['ralph_auth']




async def get_request_token(url: str, end_point: str):
    """Fetch a Kroger OAuth2 client-credentials access token.

    Sends a POST request to `{url}{end_point}` using HTTP Basic auth built
    from the KROGER_CLIENT_ID / KROGER_CLIENT_SECRET environment variables,
    requesting the client_credentials grant with the "product.compact" scope.

    Args:
        url: Base API URL, e.g. the `ralph_store` value from setup.yaml
            ("https://api.kroger.com/v1").
        end_point: Path appended directly to `url` to form the full request
            URL, e.g. the `ralph_auth` value from setup.yaml
            ("connect/oauth2/token"). No separator is inserted, so include
            any needed "/" in `url` or `end_point`.

    Returns:
        str: The access token string on success.
        int: The HTTP status code if the request fails (non-2xx response).
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{url}{end_point}",
                auth=(os.environ["KROGER_CLIENT_ID"], os.environ["KROGER_CLIENT_SECRET"]),
                data={"grant_type": "client_credentials", "scope": "product.compact"},
            )
            resp.raise_for_status()
            token = resp.json()["access_token"]
            return token
    except httpx.HTTPStatusError as e:
        return e.response.status_code


async def get_stores(token: str, url: str, end_point: str, params: dict):
    """Look up Kroger store locations.

    Sends a GET request to `{url}{end_point}` with the given bearer token
    and query params, e.g. for the Kroger "/locations" endpoint.

    Args:
        token: Access token string as returned by `get_request_token`, sent
            as "Authorization: Bearer {token}".
        url: Base API URL, e.g. the `ralph_store` value from setup.yaml
            ("https://api.kroger.com/v1").
        end_point: Path appended directly to `url` to form the full request
            URL, e.g. "/locations". No separator is inserted, so include any
            needed "/" in `url` or `end_point`.
        params: Query parameters dict passed through to the request, e.g.
            {"filter.zipCode.near": "92101", "filter.chain": "Ralphs"}.

    Returns:
        dict: The parsed JSON response body on success.
        int: The HTTP status code if the request fails (non-2xx response).
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{url}{end_point}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as e:
        return e.response.status_code

#later convert this to mcp resource to that it comverts it to a standard reponse format to be used later, for now we just use it as hardcoded
def parse_stores_response(stores_data: dict) -> Any:
    """Placeholder for shaping the raw Kroger /locations response.

    TODO: extract/trim the fields the caller actually needs instead of
    passing the raw Kroger response straight through.

    Args:
        stores_data: Parsed JSON dict as returned by `get_stores`.

    Returns:
        The data in whatever shape downstream callers expect.
    """
    return stores_data


@mcp.tool()
async def get_ralphs_nearest_stores(pin_code: str) -> str:
    """Find the nearest Ralphs stores to a given zip code.

    Fetches an access token, looks up nearby Kroger/Ralphs locations for
    `pin_code`, and returns the result as a JSON string.

    Args:
        pin_code: Zip code to search near, e.g. "92101".

    Returns:
        str: JSON-encoded store data, or a JSON-encoded message if no
            stores were found.
    """
    token = await get_request_token(store_api, auth_endpoint)

    params = dict(data["params"]["stores_param"])
    params["filter.zipCode.near"] = pin_code

    stores_data = await get_stores(token, store_api, "/locations", params)

    if not stores_data:
        return json.dumps({"message": "could not find the nearest stores"})

    parsed = parse_stores_response(stores_data)
    return json.dumps(parsed)
