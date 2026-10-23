# MCP Bridge

Team **Triangulate** · Amazon Developer Hackathon 2026, Alexa+ track.

A business brings its API; MCP Bridge maps it to MCP tools, generates the MCP server, and
serves it at one URL per service. Each Alexa+ user connects their own account, and every call
runs with that user's credentials: **the URL picks the service, the token picks the user.**

```
Owner Portal            Review Console               Alexa+ app
upload manifest   ──▶   try with test account  ──▶   find → connect (OAuth) → publish → ask
8 automated checks      approve → catalog            tools generated once → /mcp/{service_uuid}
```

- **Owner Portal** (`/owner`): a business uploads its API as a connector manifest (OpenAPI +
  voice phrases and answer templates + account linking), passes 8 automated checks, previews
  the MCP tools and submits.
- **Review Console** (`/review`): Amazon tries every tool against the business's real API with
  its test account, then approves (the service enters the catalog) or rejects with a reason.
- **Alexa+ app** (`/client`): a user finds the service, connects with OAuth and publishes it.
  The first publish generates the MCP server (one sanitized, verified tool file per endpoint);
  later users share it. Then they ask in plain words (Ask) or call tools directly (Tools).

More: [docs/architecture.md](docs/architecture.md) (pipeline, data, safety) and
[docs/demo-script.md](docs/demo-script.md) (the demo, step by step).

## Run it locally

Needs Docker and Node 20.19+.

```bash
cp .env.example .env          # then set the values below for a laptop
docker compose --profile app up -d --build --wait     # Postgres, Redis, mocks, seed, API + gateway
cd frontend && npm install && npm run dev             # http://localhost:3000
```

| `.env` | Laptop value | What it does |
|---|---|---|
| `VERIFY` | `skip` | Generated tools are checked by loading them (`llm` calls each one through Bedrock) |
| `APP_TOKEN_PROVIDER` | `local` | Users' OAuth tokens encrypted in Postgres (`secrets` = AWS Secrets Manager) |
| `ASSISTANT` | `rules` | How Ask mode picks a tool: phrase matching (`rules`, no AWS) or Bedrock (`llm`) |
| `ASSISTANT_MODEL_ID` | unset | Model for `ASSISTANT=llm` (must support tool use; default `BEDROCK_MODEL_ID`) |
| `POSTGRES_PORT` | `5433` | Only if Postgres is also installed on this machine (it takes 5432); use `:5433` in `DATABASE_URL` too |
| `RATE_LIMIT_PER_MINUTE` | unset (60) | Tool calls per user per minute on `/mcp` |

All app data lives in Postgres and is seeded on every `up` (only what is missing is added). Start
over with `docker compose --profile app down -v`.

## Demo data

| Who | Accounts (no password) |
|---|---|
| Alexa+ users | `alice`, `bob` (any other name signs in as a new user) |
| Business owners | Dana Okafor (Demo Bistro), Sam Lee (Lakeside Dental + Grill), Priya Shah (Pine & Petal, pending review), Taylor Brooks (FreshCart, nothing submitted yet), Marco Diaz (QuickFix, rejected) |
| Amazon reviewer | Jordan Rivera |

| Service | Mock API | State after seeding |
|---|---|---|
| Demo Bistro | `:9000` | In the catalog; order A1042 differs for Alice and Bob |
| Lakeside Dental | `:9300/dental` | In the catalog; Bob's sign-in is expired (reconnect flow) |
| Lakeside Grill | `:9300/grill` | In the catalog |
| Pine & Petal | `:9300/florist` | Waiting for review; `frontend/public/examples/pinepetal-1.1.json` is its next version |
| FreshCart Grocery | `:9300/grocery` | Not submitted; upload `frontend/public/examples/freshcart-1.0.json` as Taylor Brooks |

The fake OAuth provider (`:9100`) approves immediately, so the sign-in popup closes by itself.

## Ask mode

`POST /assistant/ask` turns what the user said into a tool call on one of their live services:

- **`ASSISTANT=rules`** (default): matches the request against each service's example phrases and
  fills arguments from the sentence (ids by the shape of the business's examples, numbers, times,
  names from the service's own list tool, search keywords). No AWS needed.
- **`ASSISTANT=llm`**: a Bedrock model picks the tool and its arguments, using the conversation so
  far (recent messages word for word, older ones as a rolling summary, all inside the `memory`
  the client sends back each turn). If Bedrock fails, that turn falls back to the rules.

Either way, code (not the model) decides the rest: whether the service is usable for this user
(connected, published, switched on, not expired), write tools ask for a yes with the business's
confirmation prompt, the call goes through the gateway with the user's own token, and the answer
comes from the business's templates. One conversation can move between services ("Lakeside
Dental: ..."), changing topic drops a pending write, and remembered ids stay with their service.

## Check it

```bash
uv run pytest                     # unit + Postgres tests (DATABASE_URL from .env)
uv run ruff check .
python scripts/e2e_check.py       # the whole flow over HTTP against the running stack
cd frontend && npm run lint && npm run build
```

`e2e_check.py` is re-runnable: steps that already happened on this database are reported as
skipped; on a fresh database (`down -v`) everything runs. `VITE_MOCK=1 npm run dev` runs the
Alexa+ app with no backend at all (an offline backup demo; the portals need the API).

## Not built yet

- **Alexa+ registration** is mocked: the Alexa+ MCP toolkit is partner-only. The MCP URL works
  with any MCP client, but nothing is registered with Alexa.
- **Alexa account linking**: users sign in with a demo username, not through Alexa.
- **AWS mode on EC2** (S3 bundles, Secrets Manager tokens, SES email) is implemented and unit
  tested, but not yet run on EC2. See [infra/README.md](infra/README.md).
- **Real third-party APIs** need per-service OAuth client credentials (today one
  `OAUTH_CLIENT_ID`/`OAUTH_CLIENT_SECRET` for all) and `client_secret_basic` token auth.
  `frontend/public/examples/kroger-1.0.json` describes Kroger's public APIs but can't run until
  then, and its hosted-copy check can only pass on kroger.com.

## Layout

```
backend/app/   api (REST + owner/review routes), auth (login, OAuth, token vault), gateway (/mcp,
               rate limit, allow-list), assistant (Ask mode: rules, LLM router, memory),
               submissions (manifest -> spec, checks, review), pipeline + codegen (generate tools),
               db (registry, portal, mapping), deploy, storage, notifications
mock-services/ catalog, demo-api, lakeside (dental, grill, florist, grocery), oauth
frontend/      React app: /owner, /review, /client; public/examples has sample manifests
contracts/     shared models (C1-C8) and fixtures, incl. api_examples.json for every route
scripts/       e2e_check.py
infra/         Dockerfile, Dockerfile.web (Caddy + built app), Caddyfile, deploy.sh
docs/          architecture.md, demo-script.md
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
