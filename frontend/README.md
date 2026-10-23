# MCP Bridge frontend

React + Vite (JavaScript) app with the three portals. All of them run on the real API and
show only data from Postgres (seeded demo data), nothing hardcoded:

| Route | Portal | API |
|---|---|---|
| `/` | Launcher: what each portal does, the demo order, what isn't built yet | `/features` |
| `/owner` | Owner Portal: connectors, detail tabs, 4-step submission wizard | `/api/owner/*` |
| `/review` | Review Console: queue, catalog, review tabs, Try it, approve and reject | `/api/review/*` |
| `/client` | Alexa+ app: sign-in, services, connect (OAuth), publish, manage, simulator (Ask and Tools) | `/auth/*`, `/services`, `/resolve-service`, `/oauth/*`, `/publish`, `/me/*`, `/assistant/ask`, `/mcp/{uuid}` |

## Run it

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run lint
npm run build    # production build in dist/
```

Needs Node 20.19+ or 22.12+ (Vite 8).

`npm run dev` expects the API on http://localhost:8000. Start it first, from the repo root:
`docker compose --profile app up -d --wait` (see the root README for `.env`). The API only allows
the origin in `FRONTEND_URL` (`http://localhost:3000`), so keep the dev server on port 3000.

| Variable | Effect |
|---|---|
| `VITE_API_URL` unset | API at http://localhost:8000 |
| `VITE_API_URL=""` | API on the same origin (the EC2 build behind Caddy) |
| `VITE_MOCK=1` | no backend: the Alexa+ app runs on `client/mockBackend.js` (offline backup demo; the portals need the API) |

Connecting opens the service's sign-in page in a popup; the local fake provider approves straight
away, so the popup closes by itself. If the browser blocks it, the app offers to retry or to sign
in in the same tab.

## Layout

```
src/
  styles/mcpbridge.css   design system shared by all portals
  components/            Toast, Overlay, ConsoleShell, AccountMenu, ToolCard, ChecksList, Switch,
                         CopyButton, PortalGate (owner/reviewer sign-in), NotBuilt (badges)
  lib/                   api.js (requests + sessions), templates.js (answer templates), portal.js
                         (API data -> ToolCard/ChecksList), config.js, Icon, helpers
  sim/                   simulator: realChatSession (Ask via /assistant/ask), mcpClient (the
                         gateway), ChatView, speech; chatSession/demoBistro/nlu for VITE_MOCK only
  data/                  the offline demo's Demo Bistro manifest and checks (VITE_MOCK only)
  launcher/              "/"
  owner/                 Owner Portal
  review/                Review Console
  client/                Alexa+ app
```

## How the screens get data

- **Alexa+ app:** one backend object (`clientState.jsx` picks it): `src/client/realBackend.js`
  (the API and gateway) or `src/client/mockBackend.js` (`VITE_MOCK=1`). Both have the same methods
  (`login`, `resolve`, `publish(userId, uuid, onProgress)`, `myServices`, `toolDefs`,
  `gatewayCall`, ...). Reads are synchronous from a cache; calls that reach the API are async. On
  a 401 the real backend signs in again and retries once. Branding, phrases, scope labels, tool
  titles, form defaults, confirmation prompts and answer templates all come from each service's
  `profile` (written by the business in its manifest).
- **Owner Portal / Review Console:** `PortalGate` signs in an owner or reviewer account (from
  `/auth/demo-users?role=...`; the API checks the role). `owner/ownerState.jsx` and
  `review/reviewState.jsx` load from the API and map it to what the screens show.
- **Not built yet:** `components/NotBuilt.jsx` reads `/features` and shows a badge where a
  feature isn't built (Alexa registration, LLM routing, account linking, AWS on EC2).

Page CSS is scoped to a body class (`owner-page`, `review-page`, `client-page`) so the portals
don't affect each other and modals rendered into `<body>` still get their styles.

The demo, step by step: [docs/demo-script.md](../docs/demo-script.md).
