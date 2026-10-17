import json

from runtime.auth_context import get_current_token


async def get_order_statusfordemo_bistro(order_id: str) -> str:
    token = get_current_token()
    return json.dumps({"order_id": order_id})
