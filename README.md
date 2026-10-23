# MCP Bridge

Amazon Developer Hackathon 2026, Alexa+ track.

A business brings its API; MCP Bridge maps it to MCP tools, generates the MCP server, and
serves it at one URL per service. Each Alexa+ user connects their own account, and every call
runs with that user's credentials: **the URL picks the service, the token picks the user.**

- **Owner Portal** (`/owner`): a business uploads its API as a connector manifest (OpenAPI +
  voice phrases + account linking), passes 8 automated checks, previews the tools, submits.
- **Review Console** (`/review`): Amazon tries the tools against the real API with the
  business's test account and approves (into the catalog) or rejects with a reason.
- **Alexa+ app** (`/client`): a user finds the service, connects with OAuth, publishes it (the
  MCP server is generated once per service), then asks in the simulator, in plain words or by
  calling tools directly.

How it fits together: [docs/architecture.md](docs/architecture.md). The demo, step by step:
[docs/demo-script.md](docs/demo-script.md).

## Run it locally

Needs Docker and Node 20.19+.

```bash
cp .env.example .env
# In .env on a laptop without AWS:
#   VERIFY=skip                 generated tools are checked by loading them, not with Bedrock
#   APP_TOKEN_PROVIDER=local    OAuth tokens encrypted in Postgres
#   POSTGRES_PORT=5433          only if Postgres is also installed on this machine (it uses 5432);
#                               then use :5433 in DATABASE_URL too
docker compose --profile app up -d --build --wait     # Postgres, Redis, mocks, seed, API + gateway
cd frontend && npm install && npm run dev             # http://localhost:3000
```

Everything the app shows comes from Postgres, seeded on every `up` with demo data (only what is
missing is added). Start over with `docker compose --profile app down -v`.

| Who | Accounts (no password) |
|---|---|
| Alexa+ users | `alice`, `bob` (any other name signs in as a new user) |
| Business owners | Dana Okafor (Demo Bistro), Sam Lee (Lakeside Dental + Grill), Priya Shah (Pine & Petal, pending review), Marco Diaz (QuickFix, rejected) |
| Amazon reviewer | Jordan Rivera |

| Service | Mock API | Notes |
|---|---|---|
| Demo Bistro | `:9000` | menu, orders; order A1042 differs per user |
| Lakeside Dental | `:9300/dental` | slots, appointments; Bob's sign-in is expired |
| Lakeside Grill | `:9300/grill` | specials, bookings |
| Pine & Petal | `:9300/florist` | waiting for review; `frontend/public/examples/pinepetal-1.1.json` is its next version |

The fake OAuth provider (`:9100`) approves immediately, so the sign-in popup closes by itself.

## Check it

```bash
uv run pytest                     # unit + Postgres tests (DATABASE_URL from .env)
uv run ruff check .
python scripts/e2e_check.py       # the whole flow over HTTP against the running stack
cd frontend && npm run lint && npm run build
```

`VITE_MOCK=1 npm run dev` runs the Alexa+ app with no backend at all (an offline backup demo).

## Not built yet

Shown in the app with a "Not built yet" badge and listed at `GET /features`:

- **Alexa+ registration** is mocked: the Alexa+ MCP toolkit is partner-only. The MCP URL works
  with any MCP client, but nothing is registered with Alexa.
- **LLM intent routing**: Ask mode matches what you say to a tool using each business's example
  phrases and answer templates, without an LLM.
- **Alexa account linking**: users sign in with a demo username.
- **AWS mode on EC2** (S3 bundles, Secrets Manager tokens, SES email) is implemented and tested,
  but not yet run on EC2. See [infra/README.md](infra/README.md).

## Layout

```
backend/app/   api (REST), auth (login, OAuth, token vault), gateway (/mcp), assistant (Ask mode),
               submissions (manifest -> spec, checks, review), pipeline + codegen (generate tools),
               db (registry, portal, mapping), deploy, storage, notifications
mock-services/ catalog, demo-api, lakeside (dental, grill, florist), oauth
frontend/      React app: /owner, /review, /client
contracts/     shared models (C1-C8) and fixtures, incl. api_examples.json for every route
scripts/       e2e_check.py
infra/         Dockerfile, Dockerfile.web (Caddy + built app), Caddyfile, deploy.sh
```
