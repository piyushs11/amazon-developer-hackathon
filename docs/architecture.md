# Architecture

MCP Bridge turns a business's API into an MCP server that Alexa+ users can use with their own
accounts. One gateway serves every service: **the URL picks the service, the user's token picks
the account.**

```
 Owner Portal (/owner)          Review Console (/review)          Alexa+ app (/client)
   upload manifest ──────────▶   try with test account ──▶ approve     find · connect · publish · ask
        │  POST /api/owner/…            │ POST /api/review/…/approve          │
        ▼                               ▼                                     ▼
 ┌──────────────────────────── FastAPI app (one process, :8000) ─────────────────────────────┐
 │ submissions/manifest.py   manifest -> C1 spec (+ profile) -> parse_spec -> map_service    │
 │ db/registry  (Postgres)   service_registry · endpoint_registry · businesses               │
 │ db/portal    (Postgres)   users · submissions · notifications                             │
 │ db/mapping   (Postgres)   user_service_mapping (status, enabled, last_called_at)          │
 │ auth/                     demo login (JWT), OAuth start/callback, token vault (encrypted) │
 │ pipeline/publish.py       generate (sanitized tool files, verified) -> deploy -> register │
 │ gateway/   POST /mcp/{uuid}  identity -> rate limit -> active bundle -> allow-list ->     │
 │                              connection (on, not expired) -> user's token -> tool          │
 │ assistant/ POST /assistant/ask  phrase matching over every live service -> gateway call   │
 └───────────────────────────────────────────────────────────────────────────────────────────┘
        │ upstream calls with the user's own token
        ▼
 mock-services: demo-api :9000 (Demo Bistro) · lakeside :9300 (dental, grill, florist)
                oauth :9100 (fake provider) · catalog :9200 (seed specs)
```

## The pipeline: API in, MCP server out

1. **Submit.** A business uploads a connector manifest: OpenAPI endpoints with `x-alexa`
   fields (example phrases, side effect, confirmation prompt, spoken answer templates), OAuth
   account linking, and a private block with a test account. Eight automated checks run on it
   (`backend/app/submissions/manifest.py`).
2. **Review.** A reviewer tries each tool against the business's real API with the test
   account, then approves or rejects with a reason. Approval converts the manifest to our format
   (C1 spec + profile -> C2 mapped endpoints) and writes it to the registry, so the service is
   in the catalog. Nothing is generated yet.
3. **Publish.** The first user who connects (OAuth) and publishes triggers generation: one
   sanitized Python tool file per endpoint, each verified to load, stored as a numbered bundle
   version, then activated on the gateway. Later users skip generation and share the bundle.
   When a reviewer approves a new version, the registry's spec hash no longer matches the
   active bundle's, the app shows "Update available", and the next publish generates the next
   version (the old one stays live until the new one loads).
4. **Use.** `POST /mcp/{service_uuid}` is a standard MCP server (initialize, tools/list,
   tools/call). Each call carries the user's token; the gateway resolves the user, checks
   their connection, gets their upstream token (refreshing it, or marking the connection
   expired), and runs the tool. Ask mode (`/assistant/ask`) picks the tool from what the user
   said, using only the business's phrases and templates, and calls the same gateway path.

## Data

All demo data is seeded into Postgres by `backend/app/db/registry/seed.py` (runs on every
`docker compose up`, only adds what is missing): the catalog services and their profiles from
`mock-services/catalog/specs/`, users, businesses, the review history and a pending submission
(`backend/app/db/registry/*_seed.json`, `manifests/`). The frontend has no hardcoded data in
real mode; `VITE_MOCK=1` keeps an offline copy of the Alexa+ app for a backup demo.

## Safety

- Generated code comes from sanitized templates; names, paths and types are checked first.
- The gateway: bare 401 without a valid token, per-user rate limit on tool calls, upstream
  allow-list (no internal addresses except configured mock targets), argument validation
  against the input schema, 30 s timeout, no stack traces or tokens in responses or logs.
- Roles (`users.role`): only owners use `/api/owner/*` (and only for their own domains), only
  reviewers use `/api/review/*`.

## Not built yet

`GET /features` (`backend/app/features.py`) lists it, and the UI shows a "Not built yet" badge
where it applies: real Alexa+ registration (mocked), LLM intent routing, Alexa account linking,
and AWS mode on EC2 (implemented, not yet run there).
