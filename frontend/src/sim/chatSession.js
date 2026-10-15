// Alexa+ conversation engine for the simulator's Ask mode.
// Plain JS (no React) so a session can outlive the component showing it: the client app keeps
// one per user while the simulator opens and closes. ChatView subscribes to it.
import { TOOLS } from '../data/tools.js';
import { SERVICE_UUID, mcpUrl } from '../data/manifest.js';
import { fmtDateTime, money, sleep } from '../lib/utils.js';
import { callTool, fill } from './demoBistro.js';
import { classify } from './nlu.js';
import { speak } from './speech.js';

const TOOL = Object.fromEntries(TOOLS.map((t) => [t.name, t]));
const YES = /^(y|yes|yeah|yep|sure|ok|okay|go ahead|confirm)\b/i;
let nextId = 1;

/**
 * @param {object} o
 * @param {object} o.acct        fake Demo Bistro account the calls run against
 * @param {'client'|'review'} o.mode
 * @param {string} o.userId      shown in the call trace
 * @param {string} [o.intro]     first thing Alexa says
 * @param {boolean} [o.linkButton] offer an "Open Services" button when the service isn't usable
 */
export function createChatSession({ acct, mode, userId, intro, linkButton = false }) {
  const listeners = new Set();
  let config = { voice: false, access: () => 'ok', onToolCall: null };
  let pending = null;
  let busy = false;
  let snap = { items: [], suggestions: [] };

  const emit = () => listeners.forEach((fn) => fn());
  const set = (patch) => { snap = { ...snap, ...patch }; emit(); };
  const push = (item) => {
    const id = nextId++;
    set({ items: [...snap.items, { id, ...item }] });
    return id;
  };
  const remove = (id) => set({ items: snap.items.filter((i) => i.id !== id) });

  const stamp = () => ({ id: nextId++, kind: 'stamp', text: fmtDateTime(new Date()) });

  function alexa(text, extra) {
    push({ kind: 'alexa', text, extra: extra || null });
    if (config.voice) speak(text, 1.02);
  }

  function trace(r) {
    const who = mode === 'review' ? 'reviewer (test account)' : userId + ' (from the user token)';
    push({
      kind: 'trace', tool: r.tool, isError: r.is_error, ms: 90 + Math.round(Math.random() * 260),
      lines: [
        'POST ' + mcpUrl(SERVICE_UUID) + ' · tools/call',
        'user_id: ' + who,
        'arguments: ' + JSON.stringify(r.arguments),
        'upstream: ' + r.request.method + ' ' + r.request.url + ' → ' + r.status,
      ],
    });
  }

  async function thinking(ms) {
    const id = push({ kind: 'thinking' });
    await sleep(ms || 650);
    remove(id);
  }

  function nextSuggestions() {
    const s = ['What is the status of order A1042', 'What wraps does Demo Bistro have', 'Order a paneer wrap from Demo Bistro'];
    if (acct.last) s.unshift('Where is my Demo Bistro order');
    return s;
  }

  function run(name, args) {
    const r = callTool(name, args, acct);
    trace(r);
    if (config.onToolCall) config.onToolCall(r);
    if (name === 'search_menu' && !r.is_error && r.data.count) return alexa(r.text, { type: 'items', items: r.data.items });
    if (name === 'place_order' && !r.is_error) { acct.last = r.data.order_id; return alexa(r.text, { type: 'receipt' }); }
    return alexa(r.text);
  }

  function askConfirm(args, readback) {
    const prompt = fill(TOOL.place_order.confirmationPrompt, { fulfillment: args.fulfillment });
    alexa(readback + ' ' + prompt, { type: 'confirm' });
    pending = args;
  }

  function blockedMessage(access) {
    if (access === 'not_connected') return 'Please connect Demo Bistro in MCP Bridge first.';
    if (access === 'expired') return 'Please reconnect Demo Bistro in MCP Bridge. Your Demo Bistro sign-in has expired.';
    if (access === 'not_published') return "Demo Bistro isn't published yet. Publish it in MCP Bridge, then ask again.";
    return null;
  }

  async function send(raw) {
    const text = (raw || '').trim();
    if (!text || busy) return;
    busy = true;
    push({ kind: 'user', text });
    set({ suggestions: [] });
    try {
      if (pending) {
        const args = pending;
        pending = null;
        // The yes/no buttons only make sense until they are answered.
        set({ items: snap.items.map((i) => (i.extra && i.extra.type === 'confirm' ? { ...i, extra: null } : i)) });
        const yes = YES.test(text);
        await thinking(yes ? 700 : 400);
        if (yes) run('place_order', args);
        else alexa("Okay, I won't place the order.");
        return;
      }

      const c = classify(text);
      await thinking(c.intent === 'unknown' ? 500 : 750);
      const needsService = ['search_menu', 'place_order', 'get_order_status'].includes(c.intent);
      const blocked = needsService ? blockedMessage(config.access()) : null;
      if (blocked) { alexa(blocked, linkButton ? { type: 'link' } : null); return; }

      switch (c.intent) {
        case 'greet':
          alexa("Hi! I can help with Demo Bistro. Ask what's on the menu, place an order, or check an order like A1042.");
          break;
        case 'search_menu':
          run('search_menu', { query: c.query });
          break;
        case 'get_order_status':
          if (!c.order_id && !acct.last) { alexa('Which order? Tell me the order ID, like A1042.'); break; }
          run('get_order_status', { order_id: c.order_id || acct.last });
          break;
        case 'place_order': {
          if (c.empty) { alexa("Which dish would you like from Demo Bistro? You can ask what's on the menu first."); break; }
          const lines = c.items.map((it) => it.quantity + ' × ' + it.item_name + ' (' + money(it.price_cents * it.quantity) + ')').join(', ');
          const sub = c.items.reduce((s, it) => s + it.price_cents * it.quantity, 0);
          const fee = c.fulfillment === 'delivery' ? 200 : 0;
          askConfirm(
            { items: c.items.map((it) => ({ item_name: it.item_name, quantity: it.quantity })), fulfillment: c.fulfillment },
            "Here's your order: " + lines + (fee ? ', plus a ' + money(fee) + ' delivery fee' : '') + '. Total ' + money(sub + fee) + '.'
          );
          break;
        }
        case 'no_tool':
          alexa("Demo Bistro doesn't let me cancel orders yet. I can search the menu, place an order or check an order's status.");
          break;
        default:
          alexa('I can help with Demo Bistro right now. Try "what wraps does Demo Bistro have" or "what is the status of order A1042".');
      }
    } finally {
      busy = false;
      if (!pending) set({ suggestions: nextSuggestions() });
    }
  }

  function reset() {
    pending = null;
    snap = { items: [stamp()], suggestions: nextSuggestions() };
    emit();
  }

  snap = { items: [stamp()], suggestions: nextSuggestions() };
  if (intro) snap.items.push({ id: nextId++, kind: 'alexa', text: intro, extra: null });

  return {
    getSnapshot: () => snap,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    send,
    reset,
    // access() -> 'ok' | 'not_connected' | 'not_published' | 'expired'; onToolCall(result); voice: boolean
    configure(patch) { config = { ...config, ...patch }; },
  };
}
