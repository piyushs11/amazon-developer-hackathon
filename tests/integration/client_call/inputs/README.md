# client_call inputs

Function under test: `call_api(ctx, tool_name, args, storage=, tool_loader=)` (`runtime/client.py`).
Earlier steps are emulated: real `generate` -> `seed_cache` -> `persist_verified` writes the
bundle to `LocalStorage`; the OAuth step is emulated by writing the users' tokens to
`creds/users/<service_uuid>/<user>.json`. The tool loader is `hit_endpoint._load_tool`, standing
in for Dev 3's `runtime/loader.py`.

| File | Feeds | Format |
|---|---|---|
| `mapped_service.json` | generator, cache seeding, bundle storage | MappedService (C2); `base_url` is `${FAKE_API_URL}`, replaced at run time |
| `fake_api.json` | the fake restaurant API | `{"routes": [{"method", "path", "requires_token": "<token>" or [tokens], "status", "body"}]}` |
| `tokens.json` | users who connected their account | `{"<user_id>": "<token>"}` |
| `call.json` | the call the gateway makes | `{"ctx": {"user_id", "service_uuid", "request_id"}, "tool_name", "args"}`; `args` includes a hostile `"token": "EVIL"` that must be ignored |

Expected output (`../expected/<case>/result.json`): `response` (the parsed JSON `call_api` returned)
and `api_requests` (what reached the fake API, with the Authorization header).
