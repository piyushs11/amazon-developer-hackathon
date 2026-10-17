# oauth

**Owner:** Dev 3

Fake OAuth provider on :9100. `GET /authorize` auto-approves and redirects with `?code=&state=`.
`POST /token` handles `authorization_code` and `refresh_token`.

The upstream account comes from `login_hint` (`alice`, `bob`, anything else → `guest`), so two
platform users get different Demo Bistro data. Access tokens last 120 s, to exercise refresh.

Run: `uvicorn --app-dir mock-services/oauth main:app --port 9100` (or `make mocks`).
