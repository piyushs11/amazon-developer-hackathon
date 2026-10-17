# gateway

**Owner:** Dev 3

`POST /mcp/{service_uuid}`: one URL per service, and the caller's bearer token picks the user.
Stateless Streamable HTTP (plain JSON answers, no sessions, `GET` returns 405).

1. `Authorization: Bearer <user token>` → `user_id` (C8). Missing or unknown → bare `401`.
2. `get_registry().get_active_bundle(uuid)` → version, path, base_url. None → `404`.
3. `runtime.loader.load(uuid, version, path)` → `TOOLS` (cached per uuid + version).
4. JSON-RPC: `initialize`, `ping`, `tools/list`, `tools/call`. Notifications → `202`.
   `tools/call` checks the user connected the service, validates arguments against `input_schema`,
   builds `CallContext` **per request**, and runs the tool with a 30 s timeout.
5. `last_called_at` updated. Logs carry request_id, user_id, tool, duration and is_error, never tokens.

`REGISTRY=memory` serves the hand-written `contracts/fixtures/bundle.demo_bistro`.
`REGISTRY=postgres` uses Dev 1's registry.
