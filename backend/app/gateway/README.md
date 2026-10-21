# gateway

**Owner:** Dev 3

`POST /mcp/{service_uuid}`: one URL per service, and the caller's bearer token picks the user.
Stateless Streamable HTTP (plain JSON answers, no sessions, `GET` returns 405).

1. `Authorization: Bearer <user token>` → `user_id` (C8). Missing or unknown → bare `401`.
2. `get_registry().get_active_bundle(uuid)` → version, bundle_path. None → `404`.
3. `runtime.loader.load(uuid, version, bundle_path)` reads Dev 2's bundle
   (`<tool>.py` files plus `<service>_tools.py`). Each tool file is compiled on its own,
   cached per uuid + version. The input schema comes from the function signature and docstring;
   `readOnlyHint` comes from `<service>_tools.py`.
4. JSON-RPC: `initialize`, `ping`, `tools/list`, `tools/call`. Notifications → `202`.
   `tools/call`:
   - checks the user connected the service
   - validates the arguments and drops any `token` argument
   - gets **this user's** token from the TokenProvider (refreshing it if needed)
   - runs the tool with `runtime.auth_context.call_with_token`, so the tool reads the token with
     `get_current_token()`; 30 s timeout
   - turns the tool's JSON string into an MCP result. The failure JSON `{"message", "status"}`
     becomes `isError`; a 401 or 403 from upstream becomes "please reconnect".
5. `last_called_at` updated. Logs carry request_id, user_id, tool, duration and is_error, never tokens.

`REGISTRY=memory` serves `contracts/fixtures/bundle.demo_bistro` (a copy of Dev 2's generator
output). `REGISTRY=postgres` uses Dev 1's registry.
