# demo-api

**Owner:** Dev 3

Fake Demo Bistro API on :9000: `GET /menu/search?query=`, `GET /orders/{order_id}`, `POST /orders`.

Requires `Authorization: Bearer ...`. It accepts `demo-token` (the fake TokenProvider) and the
fake OAuth access tokens. Data differs per account. Order `A1042` is:

| account | status |
|---|---|
| alice | out for delivery |
| bob | being prepared |
| guest | delivered |
| demo (`demo-token`) | ready for pickup |

Run: `uvicorn --app-dir mock-services/demo-api main:app --port 9000` (or `make mocks`).
