# Demo script (about 3 minutes)

Start from a fresh database so the story runs in order:

```bash
docker compose --profile app down -v          # wipes local demo data
docker compose --profile app up -d --build --wait
cd frontend && npm run dev                    # http://localhost:3000
```

Use two browser windows: one for the portals, one sized like a phone for the Alexa+ app.

## 1. The business brings its API (30 s)

Owner Portal (`/owner`) → **Priya Shah** (Pine & Petal). Show the connector waiting for review:
the manifest (OpenAPI + `x-alexa` phrases and templates), the 8 automated checks (warnings
only for what the local demo allows), and the 2 MCP tools it turns into.

## 2. Amazon reviews it (40 s)

Review Console (`/review`) → **Jordan Rivera** → Pine & Petal 1.0 → **Start review**.
**Try it** → `search_bouquets` (occasion: birthday): a real call to the florist API with the
owner's test account, and what Alexa would say. `order_bouquet` asks first → Yes.
**Approve**. Pine & Petal is now in the catalog; nothing is generated yet.

## 3. The MCP server is created (40 s)

Alexa+ app (`/client`) → **Alice** → Services → search `pinepetal.test` → **Connect** (OAuth
popup) → **Publish**: Generating (one tool file per endpoint, sanitized and verified) →
Deploying (bundle active on the gateway) → Registering (mocked). One MCP URL:
`/mcp/{service_uuid}`.

## 4. Alice uses it (30 s)

**Try it in the simulator** → "show me roses from Pine & Petal" → "send Classic Red Roses to
Mom from Pine & Petal" → Alexa asks first → **Yes**. The trace shows the tool, the arguments,
Alice's user id from her token, and the upstream call.

## 5. Same URL, another user (20 s)

More → **Bob** → connect Pine & Petal → Publish finishes instantly (same bundle, same URL).
For Demo Bistro, "what is the status of order A1042" gives Bob his order, not Alice's.

## 6. The business ships an update (30 s)

Owner Portal → Pine & Petal → **New submission** → upload `frontend/public/examples/
pinepetal-1.1.json` (adds order tracking) → checks → 3 tools → submit. Review Console →
approve 1.1. Alice's card shows **Update available** → Update → version 2 is generated →
"where is my Pine & Petal order PP100".

## Extras if there is time

- "Lakeside" → Which one? (Dental in Evanston, Grill in Chicago); "Lakeside in Chicago" picks one.
- Bob's Lakeside Dental shows **Reconnect needed** → reconnect.
- The on/off switch: switched off, Alexa says so; the gateway refuses the call.
- QuickFix in the Review Console: a rejected submission and its failed checks.
- Launcher (`/`): the "Not built yet" list.

Check everything at once: `python scripts/e2e_check.py` (all checks pass on a fresh database).
