"""Fake Demo Bistro API (:9000). Requires a bearer token; data differs per account.

Accepted tokens: the fake provider's "demo-token" (account "demo") and the
fake OAuth server's "demo-access.{account}.{expires_at}.{nonce}".
"""
import itertools
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Demo Bistro API")

MENU = [
    {"name": "Spaghetti Carbonara", "price": 14.5, "tags": ["pasta"]},
    {"name": "Penne Arrabbiata", "price": 12.0, "tags": ["pasta", "spicy"]},
    {"name": "Margherita Pizza", "price": 11.0, "tags": ["pizza", "vegetarian"]},
    {"name": "Caesar Salad", "price": 9.5, "tags": ["salad"]},
    {"name": "Tiramisu", "price": 6.5, "tags": ["dessert"]},
]

# Same order id, different status per account: makes user isolation visible.
ORDERS = {
    "alice": {"A1042": {"status": "out for delivery", "item": "Spaghetti Carbonara", "eta_minutes": 10}},
    "bob": {"A1042": {"status": "being prepared", "item": "Margherita Pizza", "eta_minutes": 25}},
    "guest": {"A1042": {"status": "delivered", "item": "Caesar Salad", "eta_minutes": 0}},
    "demo": {"A1042": {"status": "ready for pickup", "item": "Tiramisu", "eta_minutes": 0}},
}
_next_id = itertools.count(2001)


def account_from_token(authorization: str | None = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token == "demo-token":
        return "demo"
    parts = token.split(".")
    if len(parts) == 4 and parts[0] == "demo-access" and parts[2].isdigit():
        if int(parts[2]) < time.time():
            raise HTTPException(401, "token expired")
        return parts[1]
    raise HTTPException(401, "invalid token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/menu/search")
def search_menu(query: str, account: str = Depends(account_from_token)) -> dict:
    q = query.lower()
    hits = [d for d in MENU if q in d["name"].lower() or q in d["tags"]]
    return {"query": query, "results": hits}


@app.get("/orders/{order_id}")
def get_order(order_id: str, account: str = Depends(account_from_token)) -> dict:
    order = ORDERS.setdefault(account, {}).get(order_id)
    if order is None:
        raise HTTPException(404, f"order {order_id} not found")
    return {"order_id": order_id, **order}


class NewOrder(BaseModel):
    item: str
    quantity: int


@app.post("/orders", status_code=201)
def place_order(body: NewOrder, account: str = Depends(account_from_token)) -> dict:
    if body.quantity < 1:
        raise HTTPException(422, "quantity must be at least 1")
    order_id = f"A{next(_next_id)}"
    ORDERS.setdefault(account, {})[order_id] = {
        "status": "received", "item": body.item, "quantity": body.quantity, "eta_minutes": 30,
    }
    return {"order_id": order_id, **ORDERS[account][order_id]}
