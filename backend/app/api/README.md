# api

**Owner:** Dev 4

REST routes (contract C7). Samples of every request and response: `contracts/fixtures/api_examples.json`.

| Route | Needs user token | What |
|---|---|---|
| `GET /oauth/start?service_uuid=` | yes | `{auth_url}` for the service's sign-in page (`auth/oauth.build_auth_url`) |
| `GET /oauth/callback?code&state` | no (signed `state`) | stores the token + connection, then 302 to `{FRONTEND_URL}/connect/done?status=ok\|error` |
| `POST /publish {service_uuid}` | yes | starts a background publish, returns `{job_id}` |
| `GET /publish/{job_id}` | yes | `{status: running\|done\|failed, stage, mcp_url?, skipped, version?, error?}` |
| `GET /me/services` | yes | `[{service_uuid, service_name, status, mcp_url, last_called_at}]` |

`POST /auth/demo-login` is in `auth/router.py`, `POST /mcp/{service_uuid}` in `gateway/router.py`.
`POST /resolve-service` is not built yet.

| File | What |
|---|---|
| `router.py` | the routes above |
| `jobs.py` | `PublishJobs`: runs `pipeline.publish.publish()` as an `asyncio` task, keeps progress per job |
| `schemas.py` | request/response models |

## Behaviour to know
- The user always comes from the token (`get_current_user`: bare 401), never from the request body.
- **Jobs live in this process's memory** and are dropped an hour after they finish. After a restart
  a client's `GET /publish/{job_id}` gives 404; it publishes again and a service that already
  went live is reported as `skipped`. A second `POST /publish` by the same user for the same
  service while one is running returns the same `job_id`. Another user's job id gives 404.
- Stages: `queued` → `generating` → `deploying` → `registering` → `done`, or `skipped` → `done`
  when the service is already live, or `failed` (with `error.step`, `error.code`, `error.message`).
- `/me/services` status: `connected` (signed in, not published), `active` (live; `mcp_url` set),
  `expired` / `revoked` (reconnect).
- Several gateway instances would each hold their own jobs (see infra/README "Scale path").
