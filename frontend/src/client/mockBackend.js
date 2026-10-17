// In-memory stand-in for the MCP Bridge backend that the client app talks to.
// Method names follow the C6/C7 contracts (demo-login, resolve-service, oauth, publish with
// progress, me/services, gateway tools/call), so wiring the real API means replacing this module.
import { MANIFEST, SCOPE_LABELS, SERVICE_UUID, mcpUrl } from '../data/manifest.js';
import { TOOLS } from '../data/tools.js';
import { daysAgo, sleep } from '../lib/utils.js';
import { callTool as callDemoBistro, seedAccount } from '../sim/demoBistro.js';

// Upstream behaviour of the other two catalog services. Demo Bistro's lives in sim/demoBistro.js.
const LD_BASE = 'https://api.lakesidedental.com/v1';
const LG_BASE = 'https://api.lakesidegrill.com/v1';
export const SLOTS = [{ id: 'slot_0914', label: 'Tue Oct 14 at 9:00 AM' }, { id: 'slot_1530', label: 'Wed Oct 15 at 2:30 PM' }, { id: 'slot_1711', label: 'Fri Oct 17 at 11:00 AM' }];
const LOCAL_TOOLS = {
  '22222222-2222-2222-2222-222222222222': [
    { name: 'next_available', title: 'Next available slots', read_only: true, sideEffect: 'none', http: { method: 'GET', baseUrl: LD_BASE, path: '/slots' },
      params: [{ name: 'visit_type', in: 'query', type: 'cleaning | checkup | emergency', required: false, description: 'Kind of visit', default: 'cleaning' }],
      run: (a) => ({ status: 200, data: { count: 3, slots: SLOTS }, text: 'The next openings for a ' + (a.visit_type || 'cleaning') + ' are ' + SLOTS[0].label + ', ' + SLOTS[1].label + ' and ' + SLOTS[2].label + '.' }) },
    { name: 'book_appointment', title: 'Book an appointment', read_only: false, sideEffect: 'write', confirm: 'Should I book your cleaning at Lakeside Dental on {slot}?', http: { method: 'POST', baseUrl: LD_BASE, path: '/appointments' },
      params: [{ name: 'slot_id', in: 'body', type: SLOTS.map((s) => s.id).join(' | '), required: true, description: 'A slot from next_available' }],
      run: (a, st) => { const s = SLOTS.find((x) => x.id === a.slot_id); if (!s) return { status: 422, data: { error: 'unknown_slot' }, text: 'Which time would you like? Ask for the next available slots first.' }; st.appt = s; return { status: 201, data: { appointment_id: 'apt_5521', slot: s }, text: 'Booked. Your cleaning is on ' + s.label + '.' }; } },
    { name: 'cancel_appointment', title: 'Cancel an appointment', read_only: false, sideEffect: 'write', confirm: 'Should I cancel your Lakeside Dental appointment?', http: { method: 'POST', baseUrl: LD_BASE, path: '/appointments/{id}/cancel' },
      params: [{ name: 'id', in: 'path', type: 'string', required: true, description: "Appointment id, or 'next'", default: 'next' }],
      run: (a, st) => { if (!st.appt) return { status: 404, data: { error: 'not_found' }, text: "You don't have an upcoming appointment at Lakeside Dental." }; const s = st.appt; st.appt = null; return { status: 200, data: { appointment_id: 'apt_5521', status: 'cancelled' }, text: 'Cancelled your appointment on ' + s.label + '.' }; } }
  ],
  '33333333-3333-3333-3333-333333333333': [
    { name: 'todays_specials', title: "Today's specials", read_only: true, sideEffect: 'none', http: { method: 'GET', baseUrl: LG_BASE, path: '/specials' }, params: [],
      run: () => ({ status: 200, data: { count: 3, items: [{ name: 'Walleye sandwich' }, { name: 'Smoked brisket' }, { name: 'Lemon tart' }] }, text: "Today's specials are walleye sandwich, smoked brisket and lemon tart." }) },
    { name: 'book_table', title: 'Book a table', read_only: false, sideEffect: 'write', confirm: 'Should I book a table for {party_size} at Lakeside Grill at {time}?', http: { method: 'POST', baseUrl: LG_BASE, path: '/bookings' },
      params: [{ name: 'party_size', in: 'body', type: 'integer', required: true, description: 'Number of people', default: 2 }, { name: 'time', in: 'body', type: 'string', required: true, description: 'For example 7:30 PM', default: '7:30 PM' }],
      run: (a) => ({ status: 201, data: { booking_id: 'bk_208', party_size: +a.party_size, time: a.time }, text: 'Booked. A table for ' + a.party_size + ' at ' + a.time + ' is held under your name.' }) }
  ]
};

export const DB = SERVICE_UUID;
export const LD = '22222222-2222-2222-2222-222222222222';
export const LG = '33333333-3333-3333-3333-333333333333';
export const CATALOG = {
  [DB]: { uuid: DB, name: 'Demo Bistro', domain: 'demobistro.test', city: 'Chicago', category: 'Food & drink', tagline: 'Search the menu, order and track it', color: '#b23a1e', initials: 'DB', glyph: 'utensils',
    description: MANIFEST.publisher.description, phrases: ['what wraps does Demo Bistro have', 'what is the status of order A1042', 'order a paneer wrap from Demo Bistro'],
    scopes: MANIFEST.accountLinking.scopes.map((s) => SCOPE_LABELS[s]), authHost: 'auth.demobistro.test', privacy: MANIFEST.publisher.privacyPolicyUrl, terms: MANIFEST.publisher.termsUrl,
    tools: TOOLS.map((t) => ({ name: t.name, title: t.title, read_only: t.read_only, sideEffect: t.sideEffect })) },
  [LD]: { uuid: LD, name: 'Lakeside Dental', domain: 'lakesidedental.com', city: 'Evanston', category: 'Health & wellness', tagline: 'Book and manage appointments', color: '#1f6f8b', initials: 'LD', glyph: 'calendar',
    description: 'Find open appointment slots and book them at Lakeside Dental.', phrases: ['when is the next cleaning at Lakeside Dental', 'book the Tuesday cleaning at Lakeside Dental'],
    scopes: ['See your appointments', 'Book appointments for you'], authHost: 'patients.lakesidedental.com', privacy: 'https://lakesidedental.com/privacy', terms: 'https://lakesidedental.com/terms' },
  [LG]: { uuid: LG, name: 'Lakeside Grill', domain: 'lakesidegrill.com', city: 'Chicago', category: 'Food & drink', tagline: 'Daily specials and table bookings', color: '#2f6b3a', initials: 'LG', glyph: 'utensils',
    description: "Lakefront grill. Hear today's specials and book a table.", phrases: ["what are today's specials at Lakeside Grill", 'book a table for two at Lakeside Grill tonight'],
    scopes: ['See specials and your bookings', 'Book tables for you'], authHost: 'login.lakesidegrill.com', privacy: 'https://lakesidegrill.com/privacy', terms: 'https://lakesidegrill.com/terms', failFirstDeploy: true }
};
Object.keys(LOCAL_TOOLS).forEach((u) => { CATALOG[u].tools = LOCAL_TOOLS[u].map((t) => ({ name: t.name, title: t.title, read_only: t.read_only, sideEffect: t.sideEffect })); });

export const PUBLISH_STAGES = ['generating', 'deploying', 'registering'];

const normalizeDomain = (q) => q.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split(/[/?#]/)[0];

function blockedText(uuid, access) {
  const n = CATALOG[uuid].name;
  if (access === 'not_connected') return 'Please connect ' + n + ' in MCP Bridge first.';
  if (access === 'expired') return 'Please reconnect ' + n + ' in MCP Bridge.';
  if (access === 'not_published') return n + " isn't published yet.";
  return null;
}

export function createMockBackend() {
  // Active bundle per service: one per service, shared by every user.
  const registry = {
    [DB]: { version: null },
    [LD]: { version: '7c41e09', published_at: daysAgo(6, 8, 2) },
    [LG]: { version: null },
  };

  const users = {
    alice: { id: 'alice', name: 'Alice', email: 'alice@example.com', color: '#126dff' },
    bob: { id: 'bob', name: 'Bob', email: 'bob@example.com', color: '#6b4ee6' },
  };
  Object.values(users).forEach((u) => { u.services = {}; u.acct = seedAccount(u.id); u.upstream = {}; });
  // Bob connected Lakeside Dental last week; his sign-in there has since expired.
  users.bob.services[LD] = { status: 'expired', on: true, account: users.bob.email, since: daysAgo(5, 18, 10), lastCalled: daysAgo(3, 19, 40) };

  let version = 0;
  const listeners = new Set();
  const changed = () => { version += 1; listeners.forEach((fn) => fn()); };

  const link = (userId, uuid) => users[userId].services[uuid];
  const isPublished = (uuid) => !!registry[uuid].version;

  // What the gateway would decide for this user and service.
  function access(userId, uuid) {
    const s = link(userId, uuid);
    if (!s) return 'not_connected';
    if (s.status === 'expired') return 'expired';
    if (!isPublished(uuid) || s.status !== 'active') return 'not_published';
    return 'ok';
  }

  function statusOf(userId, uuid) {
    const s = link(userId, uuid);
    if (s.status === 'expired') return { cls: 'err', label: 'Reconnect needed' };
    if (s.status === 'failed') return { cls: 'err', label: 'Publish failed' };
    if (s.status === 'connected') return { cls: 'warn', label: 'Ready to publish' };
    if (!s.on) return { cls: '', label: 'Off' };
    return { cls: 'live', label: 'Live' };
  }

  return {
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    getVersion: () => version,

    catalog: CATALOG,
    users: () => Object.values(users),
    user: (id) => users[id],
    link,
    isPublished,
    registry: (uuid) => registry[uuid],
    access,
    statusOf,

    // POST /auth/demo-login
    login(username) {
      return users[String(username || '').trim().toLowerCase()] || null;
    },

    // GET /me/services
    myServices(userId) {
      return Object.keys(users[userId].services).map((uuid) => ({ uuid, ...CATALOG[uuid], ...users[userId].services[uuid] }));
    },

    // POST /resolve-service. A URL or domain resolves exactly; a name can match several services.
    resolve(input) {
      const raw = String(input || '').trim();
      if (!raw) return null;
      if (/[./]/.test(raw)) {
        const domain = normalizeDomain(raw);
        const hit = Object.values(CATALOG).find((s) => s.domain === domain);
        return { query: domain, result: hit ? { status: 'resolved', uuid: hit.uuid } : { status: 'not_found', domain } };
      }
      const words = raw.toLowerCase().split(/\s+/);
      const hits = Object.values(CATALOG).filter((s) => words.every((w) => s.name.toLowerCase().includes(w)));
      const result = hits.length === 1 ? { status: 'resolved', uuid: hits[0].uuid }
        : hits.length ? { status: 'ambiguous', uuids: hits.map((h) => h.uuid) }
          : { status: 'not_found', name: raw };
      return { query: raw, result };
    },

    // GET /oauth/callback: the user signed in on the service's page and allowed access.
    completeOAuth(userId, uuid) {
      const prev = link(userId, uuid);
      if (prev && prev.status === 'expired') {
        prev.status = isPublished(uuid) ? 'active' : 'connected';
        prev.since = new Date();
        changed();
        return { reconnected: true };
      }
      users[userId].services[uuid] = { status: 'connected', on: true, account: users[userId].email, since: new Date(), lastCalled: null };
      changed();
      return { reconnected: false };
    },

    // POST /publish, then poll GET /publish/{job_id}. onProgress gets each stage as it starts,
    // or 'skipped' when the service already has an active bundle.
    async publish(userId, uuid, onProgress) {
      const reg = registry[uuid];
      const done = (skipped) => {
        const svc = link(userId, uuid);
        if (svc) svc.status = 'active';
        changed();
        return { status: 'done', skipped, mcp_url: mcpUrl(uuid) };
      };
      if (reg.version) {
        onProgress('skipped');
        await sleep(500);
        return done(true);
      }
      // Lakeside Grill's first deploy fails so the retry path can be shown.
      const failAt = CATALOG[uuid].failFirstDeploy && !reg.triedOnce ? 1 : -1;
      reg.triedOnce = true;
      for (let i = 0; i < PUBLISH_STAGES.length; i++) {
        onProgress(PUBLISH_STAGES[i]);
        await sleep(i === 0 ? 1300 : i === 1 ? (i === failAt ? 1800 : 1100) : 800);
        if (i === failAt) {
          const svc = link(userId, uuid);
          if (svc) svc.status = 'failed';
          changed();
          return { status: 'failed', error: { step: 'deploy', code: 'BUNDLE_LOAD_FAILED', message: "The new bundle didn't load in the gateway." } };
        }
      }
      reg.version = Math.random().toString(16).slice(2, 9);
      reg.published_at = new Date();
      return done(false);
    },

    setEnabled(userId, uuid, on) {
      const s = link(userId, uuid);
      if (s) { s.on = on; changed(); }
    },

    // Revokes the upstream token and deletes it. The service stays published for other users.
    disconnect(userId, uuid) {
      delete users[userId].services[uuid];
      changed();
    },

    touch(userId, uuid) {
      const s = link(userId, uuid);
      if (s) { s.lastCalled = new Date(); changed(); }
    },

    // Services this user can call in the simulator's Tools mode.
    publishedFor(userId) {
      return Object.keys(users[userId].services).filter(isPublished);
    },

    // tools/list for one service, with what the Tools form needs.
    toolDefs(uuid) {
      if (uuid === DB) {
        return TOOLS.map((t) => ({ name: t.name, title: t.title, read_only: t.read_only, sideEffect: t.sideEffect, params: t.params, http: t.http, confirm: t.confirmationPrompt }));
      }
      return LOCAL_TOOLS[uuid];
    },

    // POST /mcp/{service_uuid} tools/call with this user's token.
    gatewayCall(userId, uuid, tool, args) {
      const u = users[userId];
      const blocked = blockedText(uuid, access(userId, uuid));
      let r;
      if (blocked) {
        r = { tool: tool.name, arguments: args, request: null, status: null, text: blocked, data: null, is_error: true };
      } else if (uuid === DB) {
        r = callDemoBistro(tool.name, args, u.acct);
      } else {
        const a = {};
        Object.keys(args).forEach((k) => { if (args[k] !== '' && args[k] != null) a[k] = args[k]; });
        let path = tool.http.path;
        const q = [];
        tool.params.forEach((pr) => {
          if (pr.in === 'path') path = path.replace('{' + pr.name + '}', encodeURIComponent(a[pr.name] || pr.default || ''));
          if (pr.in === 'query' && a[pr.name]) q.push(pr.name + '=' + encodeURIComponent(a[pr.name]));
        });
        const state = u.upstream[uuid] || (u.upstream[uuid] = {});
        const out = tool.run(a, state);
        r = {
          tool: tool.name, arguments: a,
          request: { method: tool.http.method, url: tool.http.baseUrl + path + (q.length ? '?' + q.join('&') : '') },
          status: out.status, text: out.text, data: out.data, is_error: out.status >= 400,
        };
      }
      if (u.services[uuid] && !blocked) u.services[uuid].lastCalled = new Date();
      changed();
      return r;
    },
  };
}
