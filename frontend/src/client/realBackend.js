// The MCP Bridge API + gateway behind the same interface as mockBackend.js, so the screens work
// with either one. Reads (link, access, statusOf, myServices, catalog) are synchronous and come
// from a cache; everything that talks to the API is async and refreshes the cache when done.
// All data comes from the API (Postgres): users, services and their profiles (branding, example
// phrases, scope labels, tool titles, confirmation prompts and answer templates).
import { ApiError, demoLogin, demoUsers, request } from '../lib/api.js';
import { fill, speak } from '../lib/templates.js';
import { sleep } from '../lib/utils.js';
import { McpError, mcpClient } from '../sim/mcpClient.js';

export { ApiError };

export const PUBLISH_STAGES = ['generating', 'deploying', 'registering'];

const initialsOf = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
const asDate = (s) => (s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z') : null);
const userFrom = (p) => ({ id: p.user_id, name: p.display_name, email: p.email, color: p.color, role: p.role });

// A safe first question: a read-only tool's example phrase (Postgres JSONB doesn't keep key
// order, so 'the first phrase' could be a write that asks to confirm).
function askPhrase(profile) {
  const reads = Object.values(profile.tools || {}).filter((t) => (t.side_effect || 'none') === 'none');
  const phrase = reads.flatMap((t) => t.example_phrases || [])[0];
  return phrase || (profile.phrases || [])[0] || '';
}

// A catalog entry for the screens, from what the API says about a service.
function entry(uuid, name, domain, profile = {}, scopes = []) {
  const labels = profile.scope_labels || {};
  return {
    uuid, name, domain: domain || '',
    city: profile.city || '', category: profile.category || '', tagline: profile.tagline || '',
    color: profile.color || '#4a5568', initials: profile.initials || initialsOf(name), glyph: profile.glyph || 'globe',
    description: profile.description || '', phrases: profile.phrases || [], askPhrase: askPhrase(profile),
    scopes: scopes.map((s) => labels[s] || s), authHost: profile.auth_host || domain || name,
    privacy: profile.privacy_url || '', terms: profile.terms_url || '',
    toolProfiles: profile.tools || {}, tools: [],
  };
}

export function createRealBackend() {
  const users = {};
  const tokens = {}; // user_id -> user token
  const links = {}; // user_id -> { uuid: { status, on, account, since, lastCalled } }
  const services = {}; // uuid -> { loaded, published, version, mcp_url }
  const failed = {}; // `${user}:${uuid}` -> true after a failed publish, until the next try
  const clients = {}; // `${user}:${uuid}` -> mcpClient
  const defs = {}; // uuid -> tool defs from tools/list
  const unread = {}; // user_id -> unread notification count
  const catalog = {};
  let catalogList = [];

  let version = 0;
  const listeners = new Set();
  const changed = () => { version += 1; listeners.forEach((fn) => fn()); };

  function ensureEntry(uuid, name, domain, profile, scopes) {
    const old = catalog[uuid];
    if (!old || profile) catalog[uuid] = { ...entry(uuid, name || old?.name || uuid, domain || old?.domain, profile || {}, scopes || []), tools: old?.tools || [] };
    return catalog[uuid];
  }

  // Demo accounts for the sign-in chips (GET /auth/demo-users).
  async function init() {
    const list = await demoUsers('user');
    list.forEach((p) => { users[p.user_id] = { ...users[p.user_id], ...userFrom(p) }; });
    changed();
  }

  async function login(username) {
    const res = await demoLogin(username);
    tokens[res.user_id] = res.user_token;
    users[res.user_id] = userFrom(res);
    await refresh(res.user_id);
    return users[res.user_id];
  }

  // Calls the API as this user. A 401 means the token expired: sign in again and retry once.
  async function asUser(userId, method, path, body) {
    try {
      return await request(method, path, { body, token: tokens[userId] });
    } catch (e) {
      if (e.status !== 401) throw e;
      await login(userId);
      return request(method, path, { body, token: tokens[userId] });
    }
  }
  const anyUser = () => Object.keys(tokens)[0];

  async function loadService(uuid) {
    let d;
    try {
      d = await asUser(anyUser(), 'GET', '/services/' + encodeURIComponent(uuid));
    } catch (e) {
      if (e.status === 404 || e.status === 422) return null;
      throw e;
    }
    const s = ensureEntry(d.service_uuid, d.service_name, d.domain, d.profile, d.scopes);
    s.tools = d.tools.map((t) => {
      const tp = s.toolProfiles[t.name] || {};
      return { name: t.name, title: tp.title || t.description, read_only: t.read_only, sideEffect: tp.side_effect || (t.read_only ? 'none' : 'write') };
    });
    services[uuid] = { loaded: true, published: d.published, version: d.version, mcp_url: d.mcp_url,
      publishedAt: asDate(d.published_at), connectedUsers: d.connected_users, updateAvailable: d.update_available };
    changed();
    return s;
  }

  // GET /services: the whole catalog (for the "Try" chips and suggestions).
  async function loadCatalog() {
    catalogList = await asUser(anyUser(), 'GET', '/services');
    catalogList.forEach((s) => { ensureEntry(s.service_uuid, s.service_name, s.domain, s.profile); });
    changed();
    return catalogList;
  }

  // GET /me/services (+ the unread notification count). Revoked connections count as not connected.
  async function refresh(userId) {
    const [rows, notes] = await Promise.all([
      asUser(userId, 'GET', '/me/services'),
      asUser(userId, 'GET', '/me/notifications').catch(() => []),
    ]);
    const next = {};
    rows.filter((r) => r.status !== 'revoked').forEach((r) => {
      if (!catalog[r.service_uuid]?.tools.length) ensureEntry(r.service_uuid, r.service_name, r.domain, r.profile);
      next[r.service_uuid] = {
        status: failed[userId + ':' + r.service_uuid] && r.status === 'connected' ? 'failed' : r.status,
        on: r.enabled, account: users[userId]?.email, since: asDate(r.connected_at), lastCalled: asDate(r.last_called_at),
        update: r.update_available,
      };
      if (r.status === 'active') services[r.service_uuid] = { ...services[r.service_uuid], published: true, mcp_url: r.mcp_url };
    });
    links[userId] = next;
    unread[userId] = notes.filter((n) => !n.read).length;
    changed();
    // Tool lists and publish details for the cards; not needed to render, so don't wait.
    Object.keys(next).filter((u) => !services[u]?.loaded).forEach((u) => { loadService(u).catch(() => {}); });
  }

  const link = (userId, uuid) => links[userId]?.[uuid];
  const isPublished = (uuid) => !!services[uuid]?.published;

  function access(userId, uuid) {
    const s = link(userId, uuid);
    if (!s) return 'not_connected';
    if (s.status === 'expired') return 'expired';
    if (s.status !== 'active') return 'not_published';
    return 'ok';
  }

  function statusOf(userId, uuid) {
    const s = link(userId, uuid);
    if (s.status === 'expired') return { cls: 'err', label: 'Reconnect needed' };
    if (s.status === 'failed') return { cls: 'err', label: 'Publish failed' };
    if (s.status === 'connected') return { cls: 'warn', label: 'Ready to publish' };
    if (s.update) return { cls: 'warn', label: 'Update available' };
    if (!s.on) return { cls: '', label: 'Off' };
    return { cls: 'live', label: 'Live' };
  }

  function client(userId, uuid) {
    const key = userId + ':' + uuid;
    return clients[key] || (clients[key] = mcpClient(uuid, () => tokens[userId]));
  }

  // One MCP call as this user -> { text, data, isError }. Signs in again once on a 401.
  async function callTool(userId, uuid, name, args) {
    try {
      return await client(userId, uuid).callTool(name, args);
    } catch (e) {
      if (!(e instanceof McpError) || e.status !== 401) throw e;
      await login(userId);
      delete clients[userId + ':' + uuid];
      return client(userId, uuid).callTool(name, args);
    }
  }

  // tools/list entry + the tool's profile -> what the Tools form needs (same shape as the mock).
  function toolDef(uuid, t) {
    const schema = t.inputSchema || {};
    const required = schema.required || [];
    const tp = catalog[uuid]?.toolProfiles?.[t.name] || {};
    const readOnly = t.annotations?.readOnlyHint ?? false;
    const examples = tp.example_args || {};
    return {
      name: t.name, title: tp.title || t.description || t.name, read_only: readOnly,
      sideEffect: tp.side_effect || (readOnly ? 'none' : 'write'), profile: tp,
      params: Object.entries(schema.properties || {}).map(([name, p]) => ({
        name, in: 'argument', required: required.includes(name), description: p.description,
        type: p.enum ? p.enum.join(' | ') : p.type === 'integer' || p.type === 'number' ? 'integer' : 'string',
        default: p.default ?? examples[name],
      })),
      confirm: tp.confirmation_prompt || (readOnly ? undefined : 'Should I run ' + (tp.title || t.name) + '?'),
    };
  }

  return {
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    getVersion: () => version,
    live: true,

    catalog,
    catalogList: () => catalogList,
    init,
    users: () => Object.values(users).filter((u) => u.role === 'user' || !u.role),
    user: (id) => users[id],
    link,
    isPublished,
    registry: (uuid) => ({ version: services[uuid]?.published ? services[uuid].version : null, ...services[uuid] }),
    access,
    statusOf,
    loadService,
    loadCatalog,
    refresh,
    unread: (userId) => unread[userId] || 0,
    login,

    myServices(userId) {
      return Object.keys(links[userId] || {}).map((uuid) => ({ uuid, ...catalog[uuid], ...links[userId][uuid] }));
    },

    // POST /resolve-service with what the user typed (a URL, a name, or "name in city").
    async resolve(input) {
      const raw = String(input || '').trim();
      if (!raw) return null;
      const res = await asUser(anyUser(), 'POST', '/resolve-service', { query: raw });
      const domain = /[./]/.test(raw) ? raw.toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split(/[/?#]/)[0] : null;
      if (res.status === 'resolved') {
        ensureEntry(res.service.service_uuid, res.service.service_name, res.service.domain);
        loadService(res.service.service_uuid).catch(() => {});
        return { query: raw, result: { status: 'resolved', uuid: res.service.service_uuid } };
      }
      if (res.status === 'ambiguous' && res.candidates?.length) {
        await Promise.all(res.candidates.map((c) => loadService(c.service_uuid).catch(() => ensureEntry(c.service_uuid, c.service_name, c.domain))));
        return { query: raw, result: { status: 'ambiguous', uuids: res.candidates.map((c) => c.service_uuid) } };
      }
      return { query: raw, result: domain ? { status: 'not_found', domain } : { status: 'not_found', name: raw } };
    },

    // GET /oauth/start -> the service's sign-in page. /oauth/callback then sends the browser to
    // /connect/done (see ConnectDone.jsx), and the caller refreshes.
    async startOAuth(userId, uuid) {
      return (await asUser(userId, 'GET', '/oauth/start?service_uuid=' + encodeURIComponent(uuid))).auth_url;
    },

    // POST /publish, then poll GET /publish/{job_id}. onProgress gets each stage as it starts,
    // or 'skipped' when the service already has an up-to-date active bundle.
    async publish(userId, uuid, onProgress) {
      const key = userId + ':' + uuid;
      const fail = (error) => {
        failed[key] = true;
        if (links[userId]?.[uuid]) links[userId][uuid].status = 'failed';
        changed();
        return { status: 'failed', error };
      };
      let job;
      try {
        job = (await asUser(userId, 'POST', '/publish', { service_uuid: uuid })).job_id;
      } catch (e) {
        return fail({ step: 'publish', code: 'API_' + (e.status || 'UNREACHABLE'), message: e.message });
      }
      let last = null;
      let misses = 0;
      for (;;) {
        let st;
        try {
          st = await asUser(userId, 'GET', '/publish/' + job);
          misses = 0;
        } catch (e) {
          if (++misses > 5) return fail({ step: 'publish', code: 'API_' + (e.status || 'UNREACHABLE'), message: e.message });
          await sleep(1500);
          continue;
        }
        if (st.stage !== last) {
          last = st.stage;
          if (st.stage === 'skipped' || PUBLISH_STAGES.includes(st.stage)) onProgress(st.stage);
        }
        if (st.status === 'failed') return fail(st.error || { step: 'publish', code: 'FAILED', message: 'Publishing failed.' });
        if (st.status === 'done') {
          if (st.skipped && last !== 'skipped') onProgress('skipped');
          delete failed[key];
          delete defs[uuid]; // a new version may have new tools
          await Promise.all([refresh(userId).catch(() => {}), loadService(uuid).catch(() => {})]);
          return { status: 'done', skipped: !!st.skipped, mcp_url: st.mcp_url, version: st.version };
        }
        await sleep(700);
      }
    },

    // PATCH /me/services/{uuid}: off = the gateway refuses this service's calls for this user.
    async setEnabled(userId, uuid, on) {
      const s = link(userId, uuid);
      if (!s) return;
      s.on = on;
      changed();
      try {
        await asUser(userId, 'PATCH', '/me/services/' + encodeURIComponent(uuid), { enabled: on });
      } catch (e) {
        s.on = !on;
        changed();
        throw e;
      }
    },

    // DELETE /me/services/{uuid}: the stored token is deleted, the service stays published.
    async disconnect(userId, uuid) {
      await asUser(userId, 'DELETE', '/me/services/' + encodeURIComponent(uuid));
      delete clients[userId + ':' + uuid];
      await refresh(userId);
    },

    touch(userId, uuid) {
      const s = link(userId, uuid);
      if (s) { s.lastCalled = new Date(); changed(); }
    },

    publishedFor(userId) {
      return Object.keys(links[userId] || {}).filter((u) => links[userId][u].status === 'active');
    },

    // tools/list through the gateway, as this user.
    async toolDefs(uuid, userId) {
      if (!catalog[uuid]?.toolProfiles || !services[uuid]?.loaded) await loadService(uuid);
      if (!defs[uuid]) {
        let tools;
        try {
          tools = await client(userId, uuid).listTools();
        } catch (e) {
          if (!(e instanceof McpError) || e.status !== 401) throw e;
          await login(userId);
          delete clients[userId + ':' + uuid];
          tools = await client(userId, uuid).listTools();
        }
        defs[uuid] = tools.map((t) => toolDef(uuid, t));
      }
      return defs[uuid];
    },

    // tools/call from the Tools panel -> the same result shape as the mock.
    async gatewayCall(userId, uuid, tool, args) {
      const a = {};
      tool.params.forEach((p) => {
        const v = args[p.name];
        if (v === '' || v == null) return;
        a[p.name] = p.type === 'integer' ? Number(v) : v;
      });
      const base = { tool: tool.name, arguments: a, request: null, status: null, data: null };
      let res;
      try {
        res = await callTool(userId, uuid, tool.name, a);
      } catch (e) {
        return { ...base, text: e.message, is_error: true, upstream: 'Not called' };
      }
      const code = typeof res.data?.status === 'number' ? res.data.status : null;
      refresh(userId).catch(() => {}); // last called, or a connection the gateway just marked expired
      return {
        ...base, data: res.data, status: code, is_error: res.isError,
        text: speak(tool.profile, res.data, { isError: res.isError, status: code, fallback: res.text }),
        upstream: 'Sent by the gateway with ' + (users[userId]?.name || userId) + "'s token" + (code ? ' → ' + code : res.isError ? '' : ' → ok'),
      };
    },

    confirmText: (tool, args) => fill(tool.confirm, args),

    // POST /assistant/ask: one turn of Ask mode across every live service.
    async ask(userId, text, pending, memory) {
      const out = await asUser(userId, 'POST', '/assistant/ask', { text, pending, memory });
      if (out.call) refresh(userId).catch(() => {});
      return out;
    },

    // The bell: GET /me/notifications; opening it marks everything read.
    async notifications(userId) {
      const list = await asUser(userId, 'GET', '/me/notifications');
      if (list.some((n) => !n.read)) {
        await asUser(userId, 'POST', '/me/notifications/read').catch(() => {});
        unread[userId] = 0;
        changed();
      }
      return list.map((n) => ({ ...n, created_at: asDate(n.created_at) }));
    },
  };
}
