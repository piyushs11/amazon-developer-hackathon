from runtime.client import ToolResult, call_api

TOOL = {
    "name": "place_order",
    "description": "Place an order for a dish.",
    "input_schema": {
        "type": "object",
        "properties": {
            "item": {"type": "string", "description": "Name of the dish to order"},
            "quantity": {"type": "integer", "description": "Number of portions"},
        },
        "required": ["item", "quantity"],
    },
    "read_only": False,
}


async def run(ctx, item: str, quantity: int) -> ToolResult:
    return await call_api(ctx, "POST", "/orders", body={"item": item, "quantity": quantity})
