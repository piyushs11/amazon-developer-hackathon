"""What the gateway imports: every tool of this bundle as (TOOL, run) pairs."""
from .endpoints import get_order_status, place_order, search_menu

TOOLS = [
    (search_menu.TOOL, search_menu.run),
    (get_order_status.TOOL, get_order_status.run),
    (place_order.TOOL, place_order.run),
]
