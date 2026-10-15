# MCP Bridge frontend

React + Vite (JavaScript) app with the three demo portals from the clickable prototype. It runs on
in-memory mock data today; the real API (`/auth/demo-login`, `/resolve-service`, `/oauth/*`,
`/publish`, `/me/services`, and the `/mcp/{service_uuid}` gateway) gets wired in later.

| Route | Portal |
|---|---|
| `/` | Launcher with the demo order |
| `/owner` | Owner Portal: connectors, detail tabs, 4-step submission wizard |
| `/review` | Amazon Review Console: queue, catalog, review tabs, Try it simulator, approve and reject |
| `/client` | Alexa+ app: demo login, services, connect (OAuth), publish, manage, simulator (Ask and Tools) |

## Run it

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run lint
npm run build    # production build in dist/
```

Needs Node 20.19+ or 22.12+ (Vite 8).

## Layout

```
src/
  styles/mcpbridge.css   design system shared by all portals
  components/            Toast, Overlay (modal and sheet), ConsoleShell, AccountMenu, ToolCard,
                         ChecksList, Switch, CopyButton
  data/                  Demo Bistro manifest, OpenAPI -> MCP tool conversion, the 8 checks
  sim/                   simulator engine: fake Demo Bistro API, intent matching, chat session,
                         speech in and out, ChatView
  lib/                   Icon, helpers, manifest JSON viewer, useBodyClass
  launcher/              "/"
  owner/                 Owner Portal
  review/                Review Console
  client/                Alexa+ app
```

## Where the backend plugs in

- `src/client/mockBackend.js` is the only place the Alexa+ app gets data from. Its methods mirror
  the C6/C7 contracts (`login`, `resolve`, `completeOAuth`, `publish(userId, uuid, onProgress)`,
  `myServices`, `gatewayCall`). Replace them with `fetch` calls to connect the real API.
- `src/owner/ownerState.jsx` and `src/review/reviewState.jsx` hold the Owner Portal and Review
  Console state; their actions are where submission and review API calls go.

Each portal keeps its demo state in memory and resets when you reload or leave it, like the
prototype. Page CSS is scoped to a body class (`owner-page`, `review-page`, `client-page`) so the
portals don't affect each other and modals rendered into `<body>` still get their styles.

## Demo walkthrough

1. Owner Portal: New submission, use the sample manifest, checks pass, submit.
2. Review Console: open Demo Bistro 1.0, Try it with the test account, Approve.
3. Alexa+ app as Alice: tap the demobistro.test chip, Connect, sign in (any password), Publish,
   then ask "what is the status of order A1042".
4. More, switch to Bob: connect Demo Bistro, Publish finishes instantly, and the same question at
   the same MCP URL gets Bob's answer, not Alice's.
5. Extras: "Lakeside" shows a pick-one list, pizzapalace.com isn't available, Lakeside Grill's first
   publish fails and can be retried, Bob's Lakeside Dental needs a reconnect.
