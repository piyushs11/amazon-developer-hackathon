// Ask mode against the real services: the same session interface as chatSession.js (ChatView
// renders either), but every turn goes to POST /assistant/ask, which picks a tool of any of the
// user's live services from their example phrases, asks before writes, calls it through the
// gateway with the user's token and answers with the business's own templates.
import { fmtDateTime, sleep } from '../lib/utils.js';
import { speak } from './speech.js';

let nextId = 1;

/**
 * @param {object} o
 * @param {string} o.userId
 * @param {(text, pending, memory) => Promise} o.ask   POST /assistant/ask as this user
 * @param {() => string[]} o.starters              first suggestions (phrases of live services)
 * @param {string} [o.intro]
 * @param {boolean} [o.linkButton]
 */
export function createRealChatSession({ userId, ask, starters, intro, linkButton = false }) {
  const listeners = new Set();
  let config = { voice: false, onToolCall: null };
  let pending = null; // an action waiting for yes/no (from the server)
  let memory = {}; // ids from earlier answers, e.g. the order just placed
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

  async function send(raw) {
    const text = (raw || '').trim();
    if (!text || busy) return;
    busy = true;
    push({ kind: 'user', text });
    set({ suggestions: [], items: snap.items.map((i) => (i.extra && i.extra.type === 'confirm' ? { ...i, extra: null } : i)) });
    const thinking = push({ kind: 'thinking' });
    let out;
    try {
      out = await ask(text, pending, memory);
    } catch (e) {
      remove(thinking);
      alexa(e.message);
      busy = false;
      set({ suggestions: starters() });
      return;
    }
    await sleep(150);
    remove(thinking);
    pending = out.pending || null;
    memory = out.memory || memory;
    const call = out.call;
    if (call && config.onToolCall) config.onToolCall(call);
    let extra = null;
    if (out.kind === 'confirm') extra = { type: 'confirm' };
    else if (out.link && linkButton) extra = { type: 'link' };
    else if (out.items?.length) {
      extra = { type: 'items', items: out.items.map((i) => ({ id: i.name, name: i.name, category: i.detail || '', price_cents: i.price != null ? Math.round(i.price * 100) : null })) };
    }
    alexa(out.reply, extra);
    busy = false;
    set({ suggestions: pending ? [] : (out.suggestions?.length ? out.suggestions : starters()) });
  }

  function reset() {
    pending = null;
    memory = {};
    snap = { items: [stamp()], suggestions: starters() };
    emit();
  }

  snap = { items: [stamp()], suggestions: starters() };
  if (intro) snap.items.push({ id: nextId++, kind: 'alexa', text: intro, extra: null });

  return {
    getSnapshot: () => snap,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    send,
    reset,
    // Ask mode decides access on the server; access/onToolCall/voice keep chatSession's shape.
    configure(patch) { config = { ...config, ...patch }; },
    // Refresh the suggestion chips (e.g. after a service was published).
    refreshSuggestions() { if (!busy && !pending) set({ suggestions: starters() }); },
  };
}
