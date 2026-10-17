from runtime.client import ToolResult, call_api

TOOL = {
    "name": "search_menu",
    "description": "Search the menu for dishes.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Dish name or keyword, e.g. pasta"}},
        "required": ["query"],
    },
    "read_only": True,
}


async def run(ctx, query: str) -> ToolResult:
    return await call_api(ctx, "GET", "/menu/search", query={"query": query})
