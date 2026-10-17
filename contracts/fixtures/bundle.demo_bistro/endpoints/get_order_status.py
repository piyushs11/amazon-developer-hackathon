from runtime.client import ToolResult, call_api

TOOL = {
    "name": "get_order_status",
    "description": "Get the status of an order by its ID.",
    "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "Order ID, e.g. A1042"}},
        "required": ["order_id"],
    },
    "read_only": True,
}


async def run(ctx, order_id: str) -> ToolResult:
    return await call_api(ctx, "GET", "/orders/{order_id}", path={"order_id": order_id})
