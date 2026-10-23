"""Fake upstream APIs for the other demo businesses (:9300), one prefix per business:

    /dental   Lakeside Dental  (slots, appointments)
    /grill    Lakeside Grill   (specials, bookings)
    /florist  Pine & Petal     (bouquets, orders)  - the service an owner submits during the demo
    /grocery  FreshCart        (products, stores, cart) - a Kroger-style grocery API to submit

Same tokens as demo-api: "demo-token" (account "demo") or the fake OAuth server's
"demo-access.{account}.{expires_at}.{nonce}". Data differs per account so user isolation shows.
"""
import itertools
import time

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Lakeside mock APIs")


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


# ---- Lakeside Dental ----
dental = APIRouter(prefix="/dental")
SLOTS = {
    "slot_0914": "Tuesday at 9:00 AM",
    "slot_1530": "Wednesday at 2:30 PM",
    "slot_1711": "Friday at 11:00 AM",
}
APPOINTMENTS: dict[str, dict[str, dict]] = {
    "bob": {"apt_5521": {"appointment_id": "apt_5521", "slot_id": "slot_0914", "label": "Tuesday at 9:00 AM",
                         "visit_type": "checkup", "status": "booked"}},
}
_apt_ids = itertools.count(5600)


def _taken() -> set[str]:
    return {a["slot_id"] for acct in APPOINTMENTS.values() for a in acct.values() if a["status"] == "booked"}


@dental.get("/slots")
def next_available(visit_type: str = "cleaning", account: str = Depends(account_from_token)) -> dict:
    free = [{"slot_id": s, "label": label, "visit_type": visit_type} for s, label in SLOTS.items() if s not in _taken()]
    return {"visit_type": visit_type, "slots": free}


class NewAppointment(BaseModel):
    slot_id: str


@dental.post("/appointments", status_code=201)
def book_appointment(body: NewAppointment, account: str = Depends(account_from_token)) -> dict:
    if body.slot_id not in SLOTS:
        raise HTTPException(404, f"slot {body.slot_id} not found")
    if body.slot_id in _taken():
        raise HTTPException(409, "slot already taken")
    apt = {"appointment_id": f"apt_{next(_apt_ids)}", "slot_id": body.slot_id, "label": SLOTS[body.slot_id],
           "visit_type": "cleaning", "status": "booked"}
    APPOINTMENTS.setdefault(account, {})[apt["appointment_id"]] = apt
    return apt


@dental.get("/appointments")
def my_appointments(account: str = Depends(account_from_token)) -> dict:
    mine = [a for a in APPOINTMENTS.get(account, {}).values() if a["status"] == "booked"]
    return {"appointments": mine}


@dental.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: str, account: str = Depends(account_from_token)) -> dict:
    apt = APPOINTMENTS.get(account, {}).get(appointment_id)
    if apt is None or apt["status"] != "booked":
        raise HTTPException(404, f"appointment {appointment_id} not found")
    apt["status"] = "cancelled"
    return apt


# ---- Lakeside Grill ----
grill = APIRouter(prefix="/grill")
SPECIALS = [
    {"name": "Walleye sandwich", "price": 17.0},
    {"name": "Smoked brisket", "price": 22.0},
    {"name": "Lemon tart", "price": 8.0},
]
BOOKINGS: dict[str, dict[str, dict]] = {
    "alice": {"BK208": {"booking_id": "BK208", "party_size": 2, "time": "7:30 PM", "status": "confirmed"}},
    "bob": {"BK208": {"booking_id": "BK208", "party_size": 6, "time": "6:00 PM", "status": "waitlisted"}},
}
_bk_ids = itertools.count(300)


@grill.get("/specials")
def todays_specials(account: str = Depends(account_from_token)) -> dict:
    return {"specials": SPECIALS}


class NewBooking(BaseModel):
    party_size: int
    time: str


@grill.post("/bookings", status_code=201)
def book_table(body: NewBooking, account: str = Depends(account_from_token)) -> dict:
    if not 1 <= body.party_size <= 12:
        raise HTTPException(422, "party_size must be 1-12")
    bk = {"booking_id": f"BK{next(_bk_ids)}", "party_size": body.party_size, "time": body.time, "status": "confirmed"}
    BOOKINGS.setdefault(account, {})[bk["booking_id"]] = bk
    return bk


@grill.get("/bookings/{booking_id}")
def get_booking(booking_id: str, account: str = Depends(account_from_token)) -> dict:
    bk = BOOKINGS.get(account, {}).get(booking_id)
    if bk is None:
        raise HTTPException(404, f"booking {booking_id} not found")
    return bk


# ---- Pine & Petal (florist) ----
florist = APIRouter(prefix="/florist")
BOUQUETS = [
    {"name": "Spring Tulips", "price": 45.0, "occasions": ["birthday", "spring", "thank you"]},
    {"name": "Classic Red Roses", "price": 65.0, "occasions": ["anniversary", "love", "roses"]},
    {"name": "Sunflower Smile", "price": 38.0, "occasions": ["birthday", "get well", "sunflowers"]},
    {"name": "White Lily Calm", "price": 55.0, "occasions": ["sympathy", "lilies"]},
]
FLOWER_ORDERS: dict[str, dict[str, dict]] = {
    "alice": {"PP100": {"order_id": "PP100", "bouquet": "Spring Tulips", "recipient": "Mom", "status": "out for delivery"}},
}
_pp_ids = itertools.count(101)


@florist.get("/bouquets")
def search_bouquets(occasion: str = "", account: str = Depends(account_from_token)) -> dict:
    q = occasion.lower().strip()
    hits = [b for b in BOUQUETS if not q or q in b["name"].lower() or any(q in o for o in b["occasions"])]
    return {"occasion": occasion, "bouquets": hits}


class NewFlowerOrder(BaseModel):
    bouquet: str
    recipient: str


@florist.post("/orders", status_code=201)
def order_bouquet(body: NewFlowerOrder, account: str = Depends(account_from_token)) -> dict:
    match = next((b for b in BOUQUETS if b["name"].lower() == body.bouquet.lower()), None)
    if match is None:
        raise HTTPException(404, f"bouquet {body.bouquet} not found")
    order = {"order_id": f"PP{next(_pp_ids)}", "bouquet": match["name"], "recipient": body.recipient,
             "price": match["price"], "status": "received"}
    FLOWER_ORDERS.setdefault(account, {})[order["order_id"]] = order
    return order


@florist.get("/orders/{order_id}")
def flower_order_status(order_id: str, account: str = Depends(account_from_token)) -> dict:
    order = FLOWER_ORDERS.get(account, {}).get(order_id)
    if order is None:
        raise HTTPException(404, f"order {order_id} not found")
    return order


# ---- FreshCart Grocery (a Kroger-style grocery API) ----
grocery = APIRouter(prefix="/grocery")
PRODUCTS = [
    {"product_id": "FC1001", "name": "Whole Milk", "brand": "FreshCart", "size": "1 gal", "price": 3.49, "aisle": "Dairy, aisle 12", "tags": ["milk", "dairy"]},
    {"product_id": "FC1002", "name": "Oat Milk", "brand": "Oatly", "size": "64 oz", "price": 4.99, "aisle": "Dairy, aisle 12", "tags": ["milk", "dairy free", "oat"]},
    {"product_id": "FC1003", "name": "Large Eggs", "brand": "FreshCart", "size": "12 ct", "price": 2.79, "aisle": "Dairy, aisle 12", "tags": ["eggs", "breakfast"]},
    {"product_id": "FC1004", "name": "Bananas", "brand": "FreshCart", "size": "1 lb", "price": 0.59, "aisle": "Produce", "tags": ["fruit", "produce"]},
    {"product_id": "FC1005", "name": "Honeycrisp Apples", "brand": "FreshCart", "size": "3 lb bag", "price": 5.99, "aisle": "Produce", "tags": ["fruit", "produce", "apples"]},
    {"product_id": "FC1006", "name": "Sourdough Bread", "brand": "Bakery Fresh", "size": "24 oz", "price": 4.29, "aisle": "Bakery", "tags": ["bread", "bakery"]},
    {"product_id": "FC1007", "name": "Peanut Butter", "brand": "Jif", "size": "16 oz", "price": 3.19, "aisle": "Aisle 7", "tags": ["spread", "breakfast"]},
    {"product_id": "FC1008", "name": "Ground Coffee", "brand": "Starbucks", "size": "12 oz", "price": 9.99, "aisle": "Aisle 5", "tags": ["coffee", "breakfast"]},
    {"product_id": "FC1009", "name": "Pasta", "brand": "Barilla", "size": "16 oz", "price": 1.89, "aisle": "Aisle 9", "tags": ["pasta", "dinner"]},
    {"product_id": "FC1010", "name": "Marinara Sauce", "brand": "Rao's", "size": "24 oz", "price": 7.49, "aisle": "Aisle 9", "tags": ["pasta", "sauce", "dinner"]},
]
STORES = [
    {"store_id": "FC-0143", "name": "FreshCart Short North", "address": "1100 N High St", "city": "Columbus", "zip": "43201"},
    {"store_id": "FC-0207", "name": "FreshCart German Village", "address": "580 S 3rd St", "city": "Columbus", "zip": "43215"},
    {"store_id": "FC-0311", "name": "FreshCart Clintonville", "address": "3500 N High St", "city": "Columbus", "zip": "43214"},
]
OUT_OF_STOCK = {("FC-0207", "FC1002")}  # oat milk is sold out in German Village
# Carts per account: Alice already has milk in hers, Bob starts empty (user isolation shows).
CARTS: dict[str, dict[str, int]] = {"alice": {"FC1001": 1}}


def _find_product(name_or_id: str) -> dict | None:
    q = name_or_id.lower().strip()
    return next((p for p in PRODUCTS if p["product_id"].lower() == q or p["name"].lower() == q), None)


def _cart(account: str) -> dict:
    lines = [{**_find_product(pid), "quantity": qty} for pid, qty in CARTS.get(account, {}).items()]
    items = [{"product_id": li["product_id"], "name": li["name"], "quantity": li["quantity"],
              "line_total": round(li["price"] * li["quantity"], 2)} for li in lines]
    return {"items": items, "item_count": sum(i["quantity"] for i in items),
            "total": round(sum(i["line_total"] for i in items), 2)}


@grocery.get("/products")
def search_products(query: str = "", store_id: str = "", account: str = Depends(account_from_token)) -> dict:
    q = query.lower().strip()
    hits = [p for p in PRODUCTS if not q or q in p["name"].lower() or any(q in t for t in p["tags"])
            or q.rstrip("s") in p["name"].lower()]
    if store_id:
        hits = [{**p, "in_stock": (store_id, p["product_id"]) not in OUT_OF_STOCK} for p in hits]
    return {"query": query, "store_id": store_id or None, "products": hits}


@grocery.get("/products/{product_id}")
def get_product(product_id: str, account: str = Depends(account_from_token)) -> dict:
    product = _find_product(product_id)
    if product is None:
        raise HTTPException(404, f"product {product_id} not found")
    return product


@grocery.get("/stores")
def search_stores(zip: str, account: str = Depends(account_from_token)) -> dict:
    near = sorted(STORES, key=lambda s: abs(int(s["zip"]) - int(zip)) if zip.isdigit() else 0)
    return {"zip": zip, "stores": near}


class CartItem(BaseModel):
    item: str
    quantity: int = 1


@grocery.post("/cart/items", status_code=201)
def add_to_cart(body: CartItem, account: str = Depends(account_from_token)) -> dict:
    product = _find_product(body.item)
    if product is None:
        raise HTTPException(404, f"product {body.item} not found")
    if not 1 <= body.quantity <= 20:
        raise HTTPException(422, "quantity must be 1-20")
    cart = CARTS.setdefault(account, {})
    cart[product["product_id"]] = cart.get(product["product_id"], 0) + body.quantity
    summary = _cart(account)
    return {"item": product["name"], "quantity": body.quantity, "price": product["price"],
            "cart_count": summary["item_count"], "cart_total": summary["total"]}


@grocery.get("/cart")
def view_cart(account: str = Depends(account_from_token)) -> dict:
    return _cart(account)


app.include_router(dental)
app.include_router(grill)
app.include_router(florist)
app.include_router(grocery)
