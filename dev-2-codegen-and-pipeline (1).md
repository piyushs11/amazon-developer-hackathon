# Dev 2 — Codegen and Pipeline

Read `00-overview-and-contracts.md` first.
**Updated Oct 10:** bundles are now generated **once per service** and served by Dev 3's gateway. Bundles expose a `TOOLS` list (not a server process), are versioned, and contain no `requirements.txt`. `publish()` skips generation when the service already has an active bundle.

## One-line goal
Turn `MappedService` (C2) into a safe, versioned tool bundle (C3) that the gateway can load, and run the whole publish flow (C6).

## End goal
By **Oct 13**:
- `generate_service()` on the C2 fixture produces a bundle matching `bundle_demo_bistro/`
- Loading the bundle's `tools.py` gives 3 `(TOOL, run)` pairs; calling `run` for `get_order_status` returns a short answer from the demo API
- `publish()` runs generate → deploy → register using fakes and reports progress, and skips generation for an already-published service

By **Oct 15**, `publish()` runs with Dev 1's real mapper and Dev 3's real `GatewayDeployer`.

## You own
```
backend/app/codegen/     # templates, sanitizer, bundle writer
backend/app/storage/     # local folder + S3
backend/app/pipeline/    # generate_service(), publish()
runtime/client.py        # call_api() used by every generated tool
```

## Inputs and outputs

| | Format | Where |
|---|---|---|
| **Input** | `MappedService` (C2) | `mapped.demo_bistro.json` until Dev 1 lands |
| **Input** | `TokenProvider` (C4) | Fake returning `"demo-token"` until Dev 3 lands |
| **Input** | `Deployer`, `Registrar` (C5) | Fakes until Dev 3 lands |
| **Output** | Bundle at `bundles/{uuid}/{version}/` (C3) | to Dev 3 (gateway), Dev 4 (preview) |
| **Output** | `GenerationResult`, `PublishResult` (C6) | to Dev 4 |
| **Output** | `runtime/client.py` | imported by generated code |

## Starting point (first PR, Oct 9–10)
`feat/codegen-runtime-client`
- `runtime/client.py` with `call_api()` and `ToolResult`, tested with recorded HTTP responses (e.g. `respx`). No live API or other dev needed.

```python
async def call_api(ctx: CallContext, method: str, path_template: str, *,
                   path: dict | None = None, query: dict | None = None,
                   body: dict | None = None, headers: dict | None = None) -> ToolResult:
    # 1. token = await token_provider().get_valid_token(ctx.user_id, ctx.service_uuid)
    # 2. url = ctx.base_url + path_template.format(**url-encoded path values)
    # 3. drop None values from query/body
    # 4. httpx request with timeout (10s) and Authorization: Bearer <token>
    # 5. non-2xx or network error -> ToolResult(text=<short message>, is_error=True)
    # 6. success -> ToolResult(text=<short speakable summary>, data=<trimmed json>)
```
Rules: never log the token; never return raw stack traces; cap `text` length.
`ctx` is built by the gateway **per request** (it carries `user_id` from the caller's token). Never cache a token or `ctx` at module level: one bundle serves every user.

## Core tasks

### 1. Sanitizer — Oct 10
Catalog text becomes Python source, so treat it as untrusted.
- Identifiers: must match `^[a-z_][a-z0-9_]*$` and not be a keyword. Dev 1 guarantees this, but **check again** and fail closed.
- Strings (descriptions, names): embed via `repr()` / JSON, never raw inside `"""..."""` or f-strings.
- Paths: only `[A-Za-z0-9_\-/{}.]`.

### 2. Templates — Oct 10–11
Jinja2 templates for:
- `endpoints/<tool>.py` — exactly the C3 shape (`TOOL` dict + `async def run(ctx, ...)`), calling `call_api`
- `tools.py` — imports every endpoint and exposes `TOOLS = [(TOOL, run), ...]`. **This is what the gateway loads.**
- `server.py` (optional) — wraps `TOOLS` in a standalone MCP server for local testing with MCP Inspector
- `manifest.json` — `{service_uuid, service_name, version, runtime_version, base_url, tools, generated_at}`

Bundles import only `runtime.*` and the standard library; **no `requirements.txt`**, because the gateway image provides dependencies. Don't rely on the design doc's `include_server` or old `FastMCP` imports.

### 3. Bundle writer + checks — Oct 11–12
- `build_bundle(mapped: MappedService) -> dict[str, str]` (filename → content)
- After rendering, every `.py` file must pass `ast.parse`; run `ruff` in tests
- Golden test: output equals `bundle_demo_bistro/` (ignore `generated_at` and `version`)
- `version` = short content hash of the rendered files (same input → same version, so re-publishing an unchanged spec is a no-op)

### 4. Test harness — Oct 12
`tests/harness.py`: import a generated bundle's `tools.py`, check `TOOLS`, and call each `run` with a test `CallContext`. Optionally run `server.py` and connect with an MCP client. Use Dev 3's `mock-services/demo-api` once it exists; recorded responses before that. Once Dev 3's gateway lands, add one test that goes through `/mcp/{uuid}`.

### 5. Storage — Oct 13
```python
class Storage(Protocol):
    def write_bundle(self, service_uuid: str, version: str, files: dict[str, str]) -> str  # returns path
    def read_bundle(self, path: str) -> dict[str, str]
```
Path layout: `bundles/{service_uuid}/{version}/`. Never overwrite an existing version.
`LocalStorage` (`$GENERATED_DIR/bundles/...`) first, `S3Storage` later (`MODE=aws`).

### 6. Pipeline — Oct 13–14
```python
async def generate_service(service_uuid) -> GenerationResult:
    # fetch spec -> parse (Dev 1) -> map (Dev 1) -> build_bundle -> storage
    # each step wrapped; failure -> StepError(step=..., code=..., message=...)

async def publish(user_id, service_uuid, on_progress) -> PublishResult:
    active = registry.get_active_bundle(service_uuid)          # Dev 1
    if active is None or spec_changed(service_uuid, active):
        on_progress("generating")  -> generate_service
        on_progress("deploying")   -> Deployer.deploy(DeployRequest(service_uuid, version, bundle_path))
        on_progress("registering") -> Registrar.register(...)
    else:
        # already published by someone: report the three steps as done instantly
    confirm user_service_mapping exists for (user_id, service_uuid)   # written by Dev 3 at OAuth callback
    on_progress("done"); return PublishResult(mcp_url=f"{GATEWAY_URL}/mcp/{service_uuid}")
```
- `user_id` is only used to confirm this user's connection; generation never depends on the user.
- Use a per-service lock so two users publishing the same service at once don't both generate.
- Pick fake or real dependencies from `MODE` via `core/wiring.py`.

### 7. Stretch — Oct 17+
- Response shaping: per tool, pick a few useful fields for the spoken `text`
- Confirmation prompt text for write tools (`read_only: false`)

## Done when
- [ ] `call_api` tests pass: success, 401, 500, timeout, path encoding
- [ ] Generated bundle equals the fixture; all files pass `ast.parse` + `ruff`
- [ ] The hostile spec cannot inject code (test: description containing `"""; import os` stays a string)
- [ ] Harness: `TOOLS` has 3 entries; `get_order_status("A1042")` returns a short answer
- [ ] Two different `CallContext.user_id`s → `call_api` asks `TokenProvider` for two different tokens
- [ ] `publish()` with fakes reports all progress steps and returns `{GATEWAY_URL}/mcp/{uuid}`
- [ ] Second `publish()` for the same service skips generation and returns the same `mcp_url`
- [ ] Same spec twice → same `version`; changed spec → new `version`

## Handoffs to watch
- **Dev 3** imports nothing from you except the bundle folder (`tools.py`, `manifest.json`) and `runtime/client.py`. Keep `call_api`'s signature and the `TOOLS` shape stable.
- **Dev 1** provides `get_active_bundle()`; until it lands, use an in-memory fake.
- **Dev 4** calls only `publish()` and `generate_service()`.

## Out of scope
Spec parsing and mapping (Dev 1), OAuth, the gateway and EC2 (Dev 3), UI (Dev 4).
