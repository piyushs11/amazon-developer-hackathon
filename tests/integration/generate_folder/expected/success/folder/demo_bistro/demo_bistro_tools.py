from mcp.server.fastmcp import FastMCP

from .search_menu import search_menufordemo_bistro
from .get_order_status import get_order_statusfordemo_bistro
from .place_order import place_orderfordemo_bistro

mcp = FastMCP("demo_bistro")

TOOLS = [
    search_menufordemo_bistro,
    get_order_statusfordemo_bistro,
    place_orderfordemo_bistro,
]

mcp.tool(annotations={"readOnlyHint": True})(search_menufordemo_bistro)
mcp.tool(annotations={"readOnlyHint": True})(get_order_statusfordemo_bistro)
mcp.tool(annotations={"readOnlyHint": False})(place_orderfordemo_bistro)

if __name__ == "__main__":
    mcp.run()