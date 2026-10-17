# verify_endpoint inputs

Function under test: `hit_endpoint(service_name, tool_name, cache=, client=, service_uuid=)`
(`backend/app/codegen/verifier/hit_endpoint.py`). Earlier steps are emulated by running the real
`generate` and `seed_cache` (real Redis, db 15).

| File | Feeds | Format |
|---|---|---|
| `mapped_service.json` | the generator and the cache seeding | MappedService (C2). `base_url` is the placeholder `${FAKE_API_URL}`, replaced with the fake API's real URL at run time |
| `fake_api.json` | the fake restaurant API | `{"routes": [{"method", "path", "requires_token": "<token>" or [tokens], "status", "body"}]}`; a request with another bearer token gets 401, an unknown route 404 |
| `llm_script.json` | the scripted stand-in for Bedrock | `{"<tool name prefix>": {<arguments the LLM picks>}, "submit_patch": {"patched_source": "", "changes": []}}` |
| `env.json` | environment variables for the run | `DEMO_BISTRO_DEV_TOKEN` (the dev token the service provider created), `AMAZON_SUPPORT_EMAIL` |
| `setup.json` | the function's arguments | `{"service_name", "tool_name", "service_uuid"}` (`null` uuid = no business lookup, the email goes to Amazon support only) |

Expected output (`../expected/<case>/result.json`): `outcome` (`verified`/`failed`), `llm_call_sequence`
(the tool names the scripted LLM was asked to call), `api_requests` (what reached the fake API,
with the Authorization header), `failure_mentions_http_401`, `emails` (to / cc / attachments).
