// Ask-mode adapter for the REAL Demo Bistro (mock-services/demo-api through the MCP gateway).
// The in-browser fake in demoBistro.js has a different menu and order model, so the real API gets
// its own intent rules, confirmation text and spoken answers. Tools are called through mcpClient.
import { NUMS } from './demoBistro.js';

export const MENU = [
  { name: 'Spaghetti Carbonara', aliases: ['spaghetti carbonara', 'carbonara', 'spaghetti'] },
  { name: 'Penne Arrabbiata', aliases: ['penne arrabbiata', 'arrabbiata', 'penne'] },
  { name: 'Margherita Pizza', aliases: ['margherita pizza', 'margherita', 'pizza'] },
  { name: 'Caesar Salad', aliases: ['caesar salad', 'caesar', 'salad'] },
  { name: 'Tiramisu', aliases: ['tiramisu'] },
];
const KEYWORDS = ['pasta', 'pizza', 'salad', 'dessert', 'spicy', 'vegetarian', 'carbonara', 'arrabbiata', 'tiramisu'];

function findDish(t) {
  for (const dish of MENU) {
    for (const alias of dish.aliases) {
      const m = t.match(new RegExp('(?:(\\d+|a|an|one|two|three|four|five|six)\\s+)?' + alias + 's?\\b'));
      if (m) return { item: dish.name, quantity: NUMS[m[1]] || 1 };
    }
  }
  return null;
}

export function classify(text) {
  const t = text.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
  const orderId = (text.match(/\b([ab]\d{4})\b/i) || [])[1];
  if (/^(hi|hello|hey|good (morning|evening|afternoon))\b/.test(t)) return { intent: 'greet' };
  if (/\bcancel\b/.test(t)) return { intent: 'no_tool' };
  if (orderId || (/\b(where|when|status|arrive|track|eta|how long)\b/.test(t) && /\b(order|food|delivery)\b/.test(t))) {
    return { intent: 'get_order_status', order_id: orderId && orderId.toUpperCase() };
  }
  if (/\b(order|get me|i want|i d like|i would like|send me|bring me|buy)\b/.test(t)) {
    const dish = findDish(t);
    return { intent: 'place_order', empty: !dish, ...(dish || {}) };
  }
  if (/\b(menu|have|dish(es)?|serve|offer|options|food)\b/.test(t) || KEYWORDS.some((k) => t.includes(k)) || /demo ?bistro/.test(t)) {
    return { intent: 'search_menu', query: KEYWORDS.find((k) => t.includes(k)) || '' };
  }
  return { intent: 'unknown' };
}

const listNames = (names) => (names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1] : names[0] || '');

// What Alexa says for a tool result. `res` is mcpClient.callTool's { text, data, isError }.
export function speak(name, res) {
  const d = res.data || {};
  if (res.isError) {
    if (name === 'get_order_status' && d.status === 404) return "I couldn't find that order on your Demo Bistro account.";
    if (d.status === 422) return "Demo Bistro didn't accept that request.";
    return res.text || 'Something went wrong talking to Demo Bistro.';
  }
  if (name === 'search_menu') {
    const hits = d.results || [];
    if (!hits.length) return "I couldn't find any dishes matching that.";
    return 'I found ' + hits.length + (hits.length === 1 ? ' dish: ' : ' dishes, including ') + listNames(hits.slice(0, 3).map((h) => h.name)) + '.';
  }
  if (name === 'get_order_status') {
    const eta = d.eta_minutes > 0 ? ' It should be with you in about ' + d.eta_minutes + ' minutes.' : '';
    return 'Order ' + d.order_id + ' is ' + d.status + (d.item ? ' (' + d.item + ').' : '.') + eta;
  }
  if (name === 'place_order') {
    return 'Done. Order ' + d.order_id + ': ' + (d.quantity || 1) + ' × ' + d.item + '. It should be ready in about ' + d.eta_minutes + ' minutes.';
  }
  return res.text;
}

export const confirmText = (c) => 'Should I order ' + c.quantity + ' × ' + c.item + ' from Demo Bistro?';

// Cards under a search answer (ChatView's "items" extra).
export const menuItems = (data) => (data?.results || []).map((h) => ({
  id: h.name, name: h.name, category: (h.tags || []).join(', '), price_cents: Math.round((h.price || 0) * 100),
}));

export const TEXTS = {
  greet: "Hi! I can help with Demo Bistro. Ask what's on the menu, order a dish, or check an order like A1042.",
  pickDish: 'Which dish would you like from Demo Bistro? Try a margherita pizza or a spaghetti carbonara.',
  noTool: "Demo Bistro doesn't let me cancel orders. I can search the menu, place an order or check an order's status.",
  unknown: 'I can help with Demo Bistro right now. Try "what pasta does Demo Bistro have" or "what is the status of order A1042".',
};

export function suggestions(acct) {
  const s = ['What is the status of order A1042', 'What pasta does Demo Bistro have', 'Order a margherita pizza from Demo Bistro'];
  if (acct.last) s.unshift('Where is order ' + acct.last);
  return s;
}

export const PHRASES = ['what pasta does Demo Bistro have', 'what is the status of order A1042', 'order a margherita pizza from Demo Bistro'];
