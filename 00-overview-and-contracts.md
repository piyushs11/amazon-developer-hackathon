# MCP Bridge — Team Plan: Overview and Contracts

**Hackathon:** Amazon Developer Hackathon 2026, Alexa+ track
**Deadline:** Oct 23, 2026 (we submit Oct 22)
**Plan date:** Oct 9, 2026
**Updated:** Oct 10, 2026 — switched to a **single MCP gateway** (one URL per service, user identified from the token). See section 1.1.

Read this file first. Each developer also has their own file:

| File | Developer | Lane |
|---|---|---|
| `01-integration-map.md` | Everyone | How the lanes connect and the merge order |
| `dev-1-catalog-and-spec.md` | Dev 1 | Catalog and spec |
| `dev-2-codegen-and-pipeline.md` | Dev 2 | Codegen and pipeline |
| `dev-3-auth-and-deploy.md` | Dev 3 | Auth, gateway and deploy |
| `dev-4-product-surface.md` | Dev 4 | Product surface |

---

## 1. What we are building

MCP Bridge lets a user pick a service, connect their account with OAuth, and click **Publish**. The platform then:

1. Reads the service's endpoint spec from a catalog
2. Turns each endpoint into an MCP tool
3. Generates a tool bundle **once per service** (not per user)
4. Publishes the bundle to the **MCP gateway**, which serves it at one URL per service: `https://<host>/mcp/{service_uuid}`
5. Registers that URL with Alexa+ (mocked if we don't get partner access)

At call time, the gateway reads the caller's token, works out which user it is, and uses **that user's** service credentials for the upstream API call.

The demo shows this end to end for one mock service, **Demo Bistro**, through our own Alexa+ simulator.

### 1.1 Architecture decision (Oct 10): single MCP gateway

| | Before | **Now** |
|---|---|---|
| What gets generated | A server per user per service | A bundle **per service** |
| Where it runs | One Lambda per user per service | **One gateway process** serving all bundles (EC2) |
| MCP URL | One per user per service | **One per service**: `/mcp/{service_uuid}` |
| How we know the user | Baked into each deployment | From the `Authorization` token on **each request** |
| Publish | Create and deploy a function | Upload bundle + mark it active (about 1 second) |

**Why:** every user of a service runs identical code; only credentials differ. Alexa+ also uses one add-on URL per service and sends the user's linked-account token on every request. One gateway is simpler to build, publishes instantly, and scales by adding identical instances behind a load balancer.

**Generated code still matters:** Dev 2 still generates one Python file per tool. The gateway loads those files instead of deploying them.

### End goal for the team
By **Oct 15**, one user can, in `MODE=local`:
open the UI → find Demo Bistro → connect via (fake) OAuth → publish → open the simulator → ask for an order status → see the right tool called and a short spoken-style answer.

Everything after that (real AWS, real Alexa registration, polish) is a bonus layered on a working demo.

---

## 2. Working rules (how we stay independent)

1. **Contracts first.** Every handoff between devs has a fixed format in `contracts/`. Changing a contract needs approval from all 4.
2. **Fixtures exist on day 0.** A sample of every format lives in `contracts/fixtures/`. You build against the sample, not against another dev's code.
3. **Your first PR is a fake.** If others depend on you, your first PR is a fake that returns the fixture. Real code comes after.
4. **One switch for fake vs real:** `MODE=local` (fakes, local folder, local Postgres) or `MODE=aws` (EC2 + S3 + Secrets Manager).
5. **Stay in your folders.** See the ownership table below. Touching another lane's folder needs that owner's review.
6. **Git:** branches named `feat/<lane>-<short-name>` (e.g. `feat/codegen-sanitizer`). No direct commits to `main`. Small PRs (~300 lines), one review, squash merge, rebase daily. Never commit `.env`.

### Default decisions (change only as a team)
- Python, with **one pinned MCP SDK version** (the v2 SDK names the server class `MCPServer`; old examples use `FastMCP`)
- Frontend: **Next.js**
- Endpoint files are **plain async functions**; the gateway registers them per service
- **Hosting:** one EC2 instance running Docker Compose (Caddy for HTTPS + FastAPI app + Postgres). The same image scales out behind a load balancer later
- **Local-first:** local folder instead of S3, Docker Postgres, fake tokens, until integration works

---

## 3. Day 0 skeleton (merge to `main` before anyone branches)

One person creates this (suggested: Dev 4). Every module folder gets an `__init__.py` and a short `README.md` saying what it takes in and returns.

```
mcp-bridge/
├── README.md
├── CONTRIBUTING.md            # the rules in section 2
├── Makefile                   # make dev | make test | make mocks
├── docker-compose.yml         # Postgres + mock services
├── .env.example               # MODE=local, ports; no secrets
├── .github/
│   ├── CODEOWNERS
│   └── workflows/ci.yml       # lint + tests
├── contracts/                 # SHARED — all 4 approve changes
│   ├── models.py              # Pydantic models for C1–C8
│   ├── interfaces.py          # TokenProvider, Deployer, Registrar, IdentityResolver
│   └── fixtures/
│       ├── spec.demo_bistro.json
│       ├── mapped.demo_bistro.json
│       ├── bundle_demo_bistro/      # hand-written generated server
│       └── api_examples.json        # REST request/response samples
├── backend/app/
│   ├── main.py
│   ├── api/                   # Dev 4
│   ├── resolver/              # Dev 1
│   ├── spec/                  # Dev 1
│   ├── mapper/                # Dev 1
│   ├── db/registry/           # Dev 1
│   ├── codegen/               # Dev 2
│   ├── pipeline/              # Dev 2
│   ├── storage/               # Dev 2
│   ├── auth/                  # Dev 3 — upstream OAuth + platform user tokens
│   ├── deploy/                # Dev 3 — publish bundle to gateway + Alexa registrar
│   └── gateway/               # Dev 3 — POST /mcp/{service_uuid}
├── runtime/                   # imported by generated bundles
│   ├── client.py              # Dev 2 — call_api()
│   ├── tokens.py              # Dev 3 — TokenProvider
│   └── loader.py              # Dev 3 — load a bundle into a tool registry
├── mock-services/
│   ├── catalog/               # Dev 1 — serves spec JSON
│   ├── demo-api/              # Dev 3 — fake restaurant API on :9000
│   └── oauth/                 # Dev 3 — fake authorize/token on :9100
├── frontend/                  # Dev 4
├── simulator/                 # Dev 4
├── infra/                     # Dev 3 — EC2 setup, Dockerfile, Caddyfile, deploy script
└── docs/                      # Dev 4
```

### The demo service: Demo Bistro
Three endpoints, used everywhere as the shared example:

| Endpoint | Method | Purpose |
|---|---|---|
| `search_menu` | GET `/menu/search?query=` | Find dishes |
| `get_order_status` | GET `/orders/{order_id}` | Order status |
| `place_order` | POST `/orders` | Place an order (write action) |

---

## 4. Contracts

### C1. `ServiceSpec` — Dev 1 internal (catalog → parser)
`contracts/fixtures/spec.demo_bistro.json`
```json
{
  "service_uuid": "11111111-1111-1111-1111-111111111111",
  "service_name": "Demo Bistro",
  "domain": "demobistro.test",
  "base_url": "http://localhost:9000",
  "auth_type": "oauth2",
  "oauth": {
    "auth_url": "http://localhost:9100/authorize",
    "token_url": "http://localhost:9100/token",
    "scopes": ["read", "order"]
  },
  "endpoints": [
    {
      "id": "get_order_status",
      "path": "/orders/{order_id}",
      "method": "GET",
      "description": "Get the status of an order by its ID.",
      "params": [
        {"name": "order_id", "type": "string", "required": true,
         "location": "path", "description": "Order ID, e.g. A1042"}
      ]
    }
  ]
}
```

### C2. `MappedService` — Dev 1 → Dev 2 (the main handoff)
`contracts/fixtures/mapped.demo_bistro.json`
```json
{
  "service_uuid": "11111111-1111-1111-1111-111111111111",
  "service_name": "Demo Bistro",
  "endpoints": [
    {
      "endpoint_id": "get_order_status",
      "tool_name": "get_order_status",
      "method": "GET",
      "description": "Get the status of an order by its ID.",
      "path_template": "/orders/{order_id}",
      "read_only": true,
      "params": [
        {"name": "order_id", "python_type": "str", "json_type": "string",
         "required": true, "location": "path", "description": "Order ID, e.g. A1042"}
      ],
      "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "Order ID, e.g. A1042"}},
        "required": ["order_id"]
      }
    }
  ]
}
```
**Guarantees from Dev 1:**
- Required params come before optional ones
- Every name is a valid Python identifier and not a reserved word
- `read_only` is true only for `GET`
- The base URL is **not** in `path_template`; the runtime supplies it

### C3. Generated bundle — Dev 2 → Dev 3 (gateway) and Dev 4 (preview)
One bundle **per service**, versioned. Stored at `bundles/{service_uuid}/{version}/` (local folder or S3).
`contracts/fixtures/bundle_demo_bistro/` (hand-written on day 0; the generator must reproduce it)
```
bundle_demo_bistro/
├── manifest.json     # {service_uuid, service_name, version, runtime_version, base_url,
│                     #  tools: [{name, read_only}], generated_at}
├── tools.py          # TOOLS = [(TOOL, run), ...] — the gateway imports only this
├── server.py         # optional: wraps TOOLS in a standalone MCP server for local testing
└── endpoints/
    └── get_order_status.py
```
**Bundle rules:**
- Bundles import only `runtime.*` and the Python standard library. No `requirements.txt`; the gateway image provides all dependencies.
- `version` is a timestamp or content hash; publishing a new version never overwrites an old one.
- No user data inside a bundle.

Every endpoint file has this shape:
```python
from runtime.client import call_api, ToolResult

TOOL = {
    "name": "get_order_status",
    "description": "Get the status of an order by its ID.",
    "input_schema": {...},
    "read_only": True,
}

async def run(ctx, order_id: str) -> ToolResult:
    return await call_api(ctx, "GET", "/orders/{order_id}", path={"order_id": order_id})
```

### C4. Runtime — Dev 2 (`client.py`) ↔ Dev 3 (`tokens.py`, gateway)
```python
# contracts/models.py
class CallContext(BaseModel):     # built by the gateway for EVERY request
    user_id: str                  # from the caller's token (C8)
    service_uuid: str             # from the URL path
    base_url: str                 # from the bundle manifest
    request_id: str               # for logs and tracing

class ToolResult(BaseModel):
    text: str               # short, speakable
    data: dict | None = None  # trimmed structured result
    is_error: bool = False

# contracts/interfaces.py
class TokenProvider(Protocol):
    async def get_valid_token(self, user_id: str, service_uuid: str) -> str: ...
```
- **Nothing user-specific comes from env vars.** The gateway passes `CallContext` into every `run(ctx, ...)`.
- Upstream tokens come **only** from `TokenProvider`, never from an env var.
- `TOKEN_PROVIDER=fake|local|secrets` is a gateway setting, not a per-bundle one.
- The fake `TokenProvider` returns `"demo-token"`, which `mock-services/demo-api` accepts.

### C5. Publish to gateway and register — Dev 3 → Dev 2
Called **once per service version**, not per user.
```python
class DeployRequest(BaseModel):
    service_uuid: str
    version: str
    bundle_path: str            # local folder or s3:// path

class DeployResult(BaseModel):
    mcp_url: str                # "{GATEWAY_URL}/mcp/{service_uuid}"
    version: str                # now the active version
    status: Literal["deployed", "failed"]
    error: str | None = None

class RegisterResult(BaseModel):
    addon_id: str
    status: Literal["registered", "mocked", "failed"]

class Deployer(Protocol):
    async def deploy(self, req: DeployRequest) -> DeployResult: ...
    # validates the bundle loads, then marks it active in the registry

class Registrar(Protocol):
    async def register(self, name: str, mcp_url: str, version: str) -> RegisterResult: ...
```

### C8. Caller identity — Dev 3 → gateway and Dev 4
The gateway must know **which user** is calling `/mcp/{service_uuid}`.
```python
class IdentityResolver(Protocol):
    async def user_from_token(self, bearer_token: str) -> str | None: ...  # user_id or None
```
- **Hackathon:** our platform issues a signed **user token** (JWT, `sub = user_id`) at demo login. The simulator sends it as `Authorization: Bearer <user token>`.
- **Real Alexa+ (stretch):** account linking against our own OAuth server; Alexa then sends that token on every request, and the same `user_from_token` resolves it.
- No token or an unknown token → bare `401`, no `WWW-Authenticate` header (Alexa+ requirement).
- Valid user but service not connected → tool returns `ToolResult(is_error=True, text="Please connect Demo Bistro in MCP Bridge first.")`.

### C6. Pipeline — Dev 2 → Dev 4
```python
class StepError(BaseModel):
    step: Literal["parse", "map", "codegen", "store", "deploy", "register"]
    code: str
    message: str

class GenerationResult(BaseModel):
    service_uuid: str
    status: Literal["ok", "failed"]
    bundle_path: str | None = None
    tools: list[str] = []
    errors: list[StepError] = []

class PublishResult(BaseModel):
    status: Literal["done", "failed"]
    mcp_url: str | None = None
    error: StepError | None = None

async def generate_service(service_uuid: str) -> GenerationResult: ...

async def publish(user_id: str, service_uuid: str,
                  on_progress: Callable[[str], None]) -> PublishResult: ...
# progress values: "generating" -> "deploying" -> "registering" -> "done" | "failed"
```
**`publish()` behaviour with the gateway:**
1. If the service has **no active bundle** (or its spec changed): generate → deploy → register.
2. If it **already has** an active bundle (another user published it): skip straight to step 3; report the skipped steps as done.
3. Always: confirm this user's connection (token stored) and return the service's `mcp_url`.

### C7. REST API — Dev 4 → frontend and simulator
Samples for every route live in `contracts/fixtures/api_examples.json`.

| Route | Request | Response |
|---|---|---|
| `POST /auth/demo-login` | `{username}` | `{user_id, user_token}` |
| `POST /resolve-service` | `{input_type, webpage_url?, name_location?}` | `{status: "resolved" \| "ambiguous" \| "not_found", service?, candidates?}` |
| `GET /oauth/start` | `?service_uuid` + user token | `{auth_url}` |
| `GET /oauth/callback` | `?code&state` | redirect to `/connect/done?status=ok\|error` |
| `POST /publish` | `{service_uuid}` + user token | `{job_id}` |
| `GET /publish/{job_id}` | — | `{status, mcp_url?, error?}` |
| `GET /me/services` | user token | `[{service_uuid, service_name, status, mcp_url, last_called_at}]` |
| `POST /mcp/{service_uuid}` | MCP JSON-RPC + user token | MCP response (the gateway; owned by Dev 3) |

All `/api` routes except demo-login and the OAuth callback take the user token in `Authorization: Bearer ...`. `mcp_url` is the **same for every user** of a service.

---

## 5. Dependency map

| Who needs | What | From | Until it's ready, use |
|---|---|---|---|
| Dev 2 | Mapped endpoints (C2) | Dev 1 | `mapped.demo_bistro.json` |
| Dev 2 | Token + demo API (C4) | Dev 3 | Fake `TokenProvider` + recorded responses |
| Dev 2 | Deploy + register (C5) | Dev 3 | Fake `Deployer` / `Registrar` |
| Dev 3 | A bundle to serve (C3) | Dev 2 | `bundle_demo_bistro/` (hand-written) |
| Dev 3 | `call_api` inside bundles (C4) | Dev 2 | Hand-written bundle calls a stub `call_api` |
| Dev 4 | Resolver + publish (C6) | Dev 1, Dev 2 | `api_examples.json` |
| Dev 4 | OAuth flow + user token (C8) | Dev 3 | Fake OAuth server + a fixed demo token |
| Dev 4 | Gateway URL for the simulator | Dev 3 | Hand-written bundle served by the gateway |

---

## 6. Timeline

| Date | Milestone |
|---|---|
| **Oct 9** | Day 0: skeleton, contracts, fixtures, first PRs (fakes) |
| **Oct 10–13** | Build: each lane passes its own "done when" checks on fixtures and fakes |
| **Oct 14** | Integrate: Dev 1 → Dev 2 (real mapped data); Dev 2 → Dev 3 (real bundle served by the local gateway) |
| **Oct 15** | First full click-through in `MODE=local` |
| **Oct 16** | Feature freeze |
| **Oct 17–21** | EC2 deploy (`MODE=aws`), polish, demo video, README |
| **Oct 22** | Submit. Oct 23 is buffer only |

### If we fall behind, cut in this order
1. Name + City resolver mode (keep URL lookup)
2. Reconnect button and `last_called_at`
3. Real S3, Secrets Manager, and `alexa-ai deploy` (ship local storage, local token store, mock registrar on EC2)

**Never cut:** Demo Bistro working end to end through the simulator.

---

## 7. Known risks
- **Alexa+ MCP Toolkit access is partner-only.** Real registration may not be possible; the mock `Registrar` and our simulator keep the demo working.
- **"Amazon Verified Service Catalog" is unverified.** Our catalog is a mock behind an interface.
- **One EC2 instance is a single point of failure.** Fine for the demo. Scale path: the same Docker image on several instances behind a load balancer, or on ECS Fargate. The gateway keeps no local state, so this needs no redesign.
- **Bundles share one process.** Acceptable because we generate the code from sanitized templates; users never upload code. Dev 2's sanitizer is a security control, not just tidiness.
- **Loading many bundles at runtime is unverified** with the pinned MCP SDK. Dev 3 spikes it on Oct 12 (see `dev-3-auth-and-deploy.md`).
