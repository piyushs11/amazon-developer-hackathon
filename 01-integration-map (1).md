# MCP Bridge — Integration Map

How the four lanes connect, in what order to merge, and how to check each connection.
Read together with `00-overview-and-contracts.md` (which defines contracts C1–C8).
**Updated Oct 10:** single MCP gateway — one URL per service, user identified from the token on each request.

---

## 1. The whole system in one picture

```
                    SETUP TIME (user clicks through the UI)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                                                                          │
 │  Dev 4: login ──POST /auth/demo-login─▶ Dev 3: issue user token     C8   │
 │                                                                          │
 │  Dev 4: S2a ──POST /resolve-service──▶ Dev 1: resolve()                  │
 │                                          └─▶ registry (Dev 1)            │
 │                                                                          │
 │  Dev 4: S2b ──GET /oauth/start──────▶ Dev 3: build_auth_url()            │
 │      popup ─▶ mock-services/oauth (Dev 3)                                │
 │             ─GET /oauth/callback────▶ Dev 3: handle_callback()           │
 │                                          └─▶ TokenStore (Dev 3)          │
 │                                                                          │
 │  Dev 4: S2c ──POST /publish─────────▶ Dev 2: publish()                   │
 │                                          │  (only if the service has no  │
 │                                          │   active bundle yet)          │
 │                                          ├─ generate_service() (Dev 2)   │
 │                                          │    ├─ parse_spec()  (Dev 1)  C1│
 │                                          │    ├─ map_service() (Dev 1)  C2│
 │                                          │    ├─ build_bundle() (Dev 2) C3│
 │                                          │    └─ Storage       (Dev 2)   │
 │                                          ├─ Deployer.deploy()  (Dev 3) C5│
 │                                          │    └─ marks bundle active     │
 │                                          └─ Registrar.register (Dev 3) C5│
 │              ◀─GET /publish/{job_id}── progress + mcp_url           C6/C7│
 └──────────────────────────────────────────────────────────────────────────┘

                    CALL TIME (Alexa+ or the simulator asks something)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │  Dev 4: simulator ─POST /mcp/{service_uuid}─▶ Dev 3: gateway             │
 │        Authorization: Bearer <user token>      ├─ user_from_token()  C8 │
 │                                                ├─ loader: active bundle  │
 │                                                │   (Dev 2 code, cached)  │
 │                                                ├─ CallContext       C4   │
 │                                                └─ run() ─▶ call_api() (Dev 2)
 │                                                     ├─ get_valid_token() (Dev 3)
 │                                                     └─ HTTP ─▶ demo-api   │
 │              ◀── ToolResult {text, data, is_error} ─────────────────  C4 │
 └──────────────────────────────────────────────────────────────────────────┘
```

**One gateway, many services, many users:** the URL picks the **service**, the token picks the **user**.

---

## 2. Every connection point (seams)

Each row is one place where two lanes' code meets. If a merge breaks something, it is almost always on one of these lines.

| # | Seam | Producer → Consumer | Function / file | Contract | Fake used before merge |
|---|---|---|---|---|---|
| S1 | Resolve service | Dev 1 → Dev 4 | `resolver.resolve()` | C7 `/resolve-service` | `api_examples.json` |
| S2 | Parse + map spec | Dev 1 → Dev 2 | `spec.parse_spec()`, `mapper.map_service()` | C1, C2 | `mapped.demo_bistro.json` |
| S3 | Registry read/write | Dev 1 → Dev 2, Dev 4 | `db.registry.*` repository functions | C1 fields | in-memory dict |
| S4 | Generated bundle | Dev 2 → Dev 3 | `bundles/{service_uuid}/{version}/` on disk / S3 | C3 | `bundle_demo_bistro/` |
| S5 | Runtime HTTP call | Dev 2 → Dev 3 | `runtime/client.py` imports `runtime/tokens.py` | C4 | `FakeTokenProvider` |
| S6 | Load a bundle | Dev 3 → Dev 2 code | `runtime/loader.py` imports the bundle's `tools.py` → `TOOLS` | C3 `TOOLS` | — |
| S7 | Publish to gateway + register | Dev 3 → Dev 2 | `Deployer.deploy()`, `Registrar.register()` | C5 | fake deployer/registrar |
| S8 | OAuth routes | Dev 3 → Dev 4 | `auth.build_auth_url()`, `auth.handle_callback()` | C7 `/oauth/*` | fake OAuth server |
| S9 | Publish | Dev 2 → Dev 4 | `pipeline.publish()` | C6, C7 `/publish` | fake publish stepping through progress |
| S10 | Simulator → gateway | Dev 4 → Dev 3 | MCP client to `/mcp/{service_uuid}` with user token | MCP protocol, C8 | hand-written bundle served by the gateway |
| S11 | Connected services list | Dev 3 → Dev 4 | `user_service_mapping` repository | C7 `/me/services` | `api_examples.json` |
| S12 | Caller identity | Dev 3 → gateway, Dev 4 | `IdentityResolver.user_from_token()`, `/auth/demo-login` | C8 | fixed demo token → `demo-user` |
| S13 | Active bundle lookup | Dev 1 → Dev 3 | registry: `get_active_bundle(service_uuid)` | C3 path + version | in-memory dict |

---

## 3. Shared files (merge-conflict hotspots)

These files are touched by more than one lane. Rules keep conflicts small.

| File | Who touches it | Rule |
|---|---|---|
| `contracts/models.py`, `contracts/interfaces.py` | All | Separate PR, all 4 approve, merge **first**, everyone rebases right after |
| `contracts/fixtures/*` | All | Change the fixture in the **same PR** as the contract change |
| `backend/app/main.py` | Dev 4 (owner), others register routers | Each lane exposes one `router` or `get_*()` factory; only Dev 4 edits `main.py` |
| `backend/app/core/config.py` | All read, Dev 4 owns | Add new settings via a small PR; never rename existing keys |
| `pyproject.toml` / `requirements` | All | Add deps in their own commit; on conflict, keep **both** lines and re-lock |
| `docker-compose.yml` | Dev 1 (Postgres), Dev 3 (mocks, Caddy, app image), Dev 4 | Each service block is owned by one lane; don't reformat others' blocks |
| `Dockerfile` | Dev 3 | One image for API + gateway. Others request dependency changes via `pyproject.toml` |
| `.env.example` | All | Append only; group by lane with a comment header |
| `Makefile` | Dev 4 | Others request targets |

### Dependency wiring (one place, no cross-imports)
Lanes never construct each other's objects directly. Dev 4 owns one factory file that picks fake or real by `MODE`:

```python
# backend/app/core/wiring.py  (owner: Dev 4)
def get_spec_source():   ...  # Dev 1: mock catalog or real catalog
def get_mapper():        ...  # Dev 1
def get_storage():       ...  # Dev 2: LocalStorage | S3Storage
def get_token_provider():...  # Dev 3: Fake | Local | SecretsManager
def get_identity():      ...  # Dev 3: FixedDemoToken | PlatformJWT
def get_deployer():      ...  # Dev 3: Fake | Gateway (validate + mark active)
def get_registrar():     ...  # Dev 3: Mock | Alexa
```
The gateway itself is mounted once in `main.py` (`app.include_router(gateway.router)`); it is not swapped by `MODE`.
Merging a real module = changing **one line** in `wiring.py`.

---

## 4. Merge order

Each step lists what merges, what it unblocks, and the check that must pass before the next step.

### Phase A — Foundation (Oct 9)
| Step | Merge | Check |
|---|---|---|
| A1 | Day 0 skeleton (Dev 4) | `make test` green on empty tests; CI runs |
| A2 | `contracts/` models + interfaces + all fixtures | `python -c "import contracts.models"`; fixtures load into models |

**Everyone branches from `main` only after A2.**

### Phase B — Fakes (Oct 9–10), any order
| Step | Merge | Unblocks |
|---|---|---|
| B1 | Dev 3: `FakeTokenProvider`, fixed demo token, `demo-api`, fake OAuth | Dev 2 tests, Dev 4 OAuth popup + simulator auth |
| B2 | Dev 1: mock catalog + 3 specs | Dev 1's own work, Dev 2's later integration |
| B3 | Dev 2: `runtime/client.py` | Gateway can serve bundles that actually call out |
| B4 | Dev 4: API routes on fakes + app shell | Click-through work |
| B5 | Dev 3: gateway serving the hand-written bundle at `/mcp/{demo uuid}` | Dev 4 simulator can start for real |

### Phase C — Lanes complete independently (Oct 10–13), any order
Each lane merges its real modules as they pass their own "done when" checks. Real modules are **not wired in yet**; `wiring.py` still points to fakes.

### Phase D — Integration (Oct 14–15), strictly in this order
| Step | Switch in `wiring.py` | Seams | Integration check |
|---|---|---|---|
| D1 | Real `parse_spec` + `map_service` | S2 | `generate_service(demo_bistro)` bundle == `bundle_demo_bistro/` |
| D2 | Real `GatewayDeployer` | S4, S6, S7, S13 | Generated (not hand-written) bundle becomes active; Inspector on `/mcp/{uuid}` lists 3 tools |
| D3 | Real token flow (fake OAuth provider, real `TokenStore`) + platform user token | S5, S8, S12 | Login → OAuth popup → token stored → `get_order_status` succeeds via the gateway |
| D4 | Real resolver + registry | S1, S3 | S2a finds Demo Bistro by URL |
| D5 | Real `publish()` in API | S9, S11 | S2c progress reaches "done"; S1 shows the service with its `mcp_url` |
| D6 | Simulator on real `mcp_url` | S10 | Simulator answers an order-status question |
| D7 | Second user | S12 | User 2 connects Demo Bistro: publish skips generation; same `mcp_url`; their calls use **their** token |

**D6 + D7 passing = the Oct 15 milestone.** Tag it: `git tag demo-local-v1`.

### Phase E — EC2 (Oct 16+)
1. Same Docker Compose stack on one EC2 instance, with Caddy for HTTPS and a domain → `https://<domain>/mcp/{uuid}` works from outside
2. Then, one line each in `wiring.py` under `MODE=aws`: `S3Storage`, `SecretsManagerTokenStore`
3. Postgres stays in Docker on the instance (RDS is a later upgrade)

Keep `MODE=local` working as the backup demo.

---

## 5. Integration tests (one per seam)

Location: `tests/integration/`. Each test runs in CI once both sides are merged.

| Test file | Seam | Asserts |
|---|---|---|
| `test_spec_to_bundle.py` | S2 → S4 | catalog spec → bundle equals fixture (ignoring `generated_at`) |
| `test_gateway_serves_bundle.py` | S4, S6, S7, S13 | `deploy()` returns `/mcp/{uuid}`; MCP `tools/list` there has 3 tools |
| `test_tool_call_with_token.py` | S5 | `get_order_status("A1042")` returns `is_error=False` with token from `TokenProvider` |
| `test_no_auth_401.py` | S12 | no token or bad token → bare `401`, no `WWW-Authenticate` header |
| `test_user_isolation.py` | S12, S5 | two users call the same `mcp_url`; each upstream request carries **that** user's token |
| `test_not_connected.py` | S12 | valid user who never connected the service → `is_error=True`, "please connect" message |
| `test_new_version_live.py` | S6, S13 | publish v2 → next call uses v2 without a restart |
| `test_oauth_roundtrip.py` | S8 | `/oauth/start` → fake authorize → `/oauth/callback` → token stored |
| `test_publish_flow.py` | S9 | `POST /publish` → poll → `done` with `mcp_url` |
| `test_end_to_end.py` | all | resolve → oauth → publish → MCP call returns an answer |

---

## 6. How a branch merges (checklist)

Before opening a PR:
- [ ] Rebased on latest `main`
- [ ] Only touched folders you own (plus allowed shared files in section 3)
- [ ] If a contract changed: separate contract PR merged first
- [ ] Your lane's unit tests pass; fixtures unchanged unless intended
- [ ] No secrets, tokens, or `.env` committed

When merging into `main`:
- [ ] CI green
- [ ] One reviewer approved (the consumer lane if it touches a seam)
- [ ] Squash merge with a clear title: `feat(codegen): ...`
- [ ] Post in team chat if the merge changes behaviour another lane relies on

---

## 7. Environment variables by lane

| Variable | Set by | Read by | Example |
|---|---|---|---|
| `MODE` | everyone | `wiring.py` | `local` / `aws` |
| `DATABASE_URL` | Dev 1 | Dev 1, Dev 3 | `postgresql://…@localhost:5432/mcpbridge` |
| `CATALOG_URL` | Dev 1 | Dev 1 | `http://localhost:9200` |
| `GENERATED_DIR` | Dev 2 | Dev 2, Dev 3 | `./generated` (bundles live under `bundles/{uuid}/{version}/`) |
| `S3_BUCKET` | Dev 2 | Dev 2, Dev 3 | `mcpbridge-bundles` (`MODE=aws` only) |
| `TOKEN_PROVIDER` | Dev 3 | `runtime/client.py` | `fake` / `local` / `secrets` |
| `TOKEN_ENC_KEY` | Dev 3 | Dev 3 | local only, never committed |
| `OAUTH_STATE_SECRET` | Dev 3 | Dev 3 | local only, never committed |
| `PLATFORM_JWT_SECRET` | Dev 3 | Dev 3 | signs user tokens; never committed |
| `DEMO_USER_TOKEN` | Dev 3 | gateway, simulator | fixed token for the fake identity resolver (local only) |
| `GATEWAY_URL` | Dev 3 | Dev 2 (`mcp_url`), Dev 4 | `http://localhost:8000` locally, `https://<domain>` on EC2 |
| `FRONTEND_URL`, `API_URL` | Dev 4 | Dev 3 (redirect), frontend | `http://localhost:3000` |

There are **no per-bundle env vars**. Everything user- or service-specific arrives in `CallContext`.

Ports: API + gateway `8000` (one process), frontend `3000`, demo-api `9000`, fake OAuth `9100`, catalog `9200`. On EC2, Caddy listens on `443` and forwards to `8000`.

---

## 8. When something breaks after a merge

| Symptom | Likely seam | First thing to check |
|---|---|---|
| Generated bundle differs from fixture | S2 / S4 | Did C2 change without updating `mapped.demo_bistro.json`? |
| Generated code has a syntax error | S2 / S4 | Param name not sanitised (Dev 1) or not escaped (Dev 2) |
| `tools/list` empty | S6 / S13 | Registry has no active version; `loader.py` importing `tools.py`; `TOOLS` list empty |
| Gateway returns 401 for the simulator | S12 | Simulator not sending `Authorization`; `DEMO_USER_TOKEN` mismatch; JWT secret differs |
| Gateway returns 404 | S13 | `service_uuid` in URL not in registry, or no active bundle |
| Tool returns 401 from demo API | S5 | `TOKEN_PROVIDER` value; token store has an entry for this user + service |
| Every tool call fails with timeout | S5 | `base_url` in the bundle manifest; demo-api running on 9000 |
| Old tool behaviour after re-publish | S6 | Loader cache keyed by `service_uuid` only — must be keyed by `(service_uuid, version)` |
| Publish stuck at "deploying" | S7 | Bundle failed to load during validation; deployer error not mapped to `StepError` |
| OAuth popup never closes | S8 | `FRONTEND_URL` in redirect; `state` signature mismatch |
| S1 doesn't show new service | S11 | OAuth callback or publish didn't write `user_service_mapping` |
| User A's call used user B's data | S12 / S5 | `CallContext` built from the URL or a cached value instead of the token — **stop and fix before demo** |
