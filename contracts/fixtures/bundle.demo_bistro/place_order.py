import json

import httpx
from runtime.auth_context import get_current_token


async def place_order_request(token: str, url: str, end_point: str, method: str, params: dict, body: dict, headers: dict):
    """Call `place_order` on demo_bistro.

    Sends a `POST` request to `{url}{end_point}` with the given bearer token.

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


async def place_orderfordemo_bistro(item: str, quantity: int | None = None) -> str:
    """Place a new order for a menu item.

    Args:
        item: Menu item name
        quantity: How many to order

    Returns:
        str: JSON-encoded response, or a JSON-encoded message if the call failed.
    """
    token = get_current_token()  # set by the caller just before this call, never by the LLM
    path_params = {
    }
    query = {
    }
    body = {
        "item": item,
        "quantity": quantity,
    }
    headers = {
    }
    query = {k: v for k, v in query.items() if v is not None}
    body = {k: v for k, v in body.items() if v is not None}
    headers = {k: str(v) for k, v in headers.items() if v is not None}

    result = await place_order_request(
        token,
        "http://localhost:9000",
        "/orders".format(**path_params),
        "POST",
        query,
        body,
        headers,
    )

    if not result or isinstance(result, int):
        return json.dumps({"message": "request to place_order failed", "status": result})

    return json.dumps(result)