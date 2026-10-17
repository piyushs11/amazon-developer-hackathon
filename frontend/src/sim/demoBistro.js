// Fake Demo Bistro API (each account has its own orders) and the gateway's tools/call for it.
import { TOOLS } from '../data/tools.js';
import { money } from '../lib/utils.js';

export const MENU = [
  { id: 'm1', name: 'Paneer Tikka Wrap', category: 'wraps', price_cents: 950, tags: ['vegetarian', 'spicy', 'wrap'] },
  { id: 'm2', name: 'Chicken Shawarma Wrap', category: 'wraps', price_cents: 1050, tags: ['wrap'] },
  { id: 'm3', name: 'Falafel Wrap', category: 'wraps', price_cents: 850, tags: ['vegan', 'vegetarian', 'wrap'] },
  { id: 'm4', name: 'Butter Chicken', category: 'mains', price_cents: 1400, tags: ['popular'] },
  { id: 'm5', name: 'Chana Masala', category: 'mains', price_cents: 1150, tags: ['vegan', 'vegetarian', 'spicy'] },
  { id: 'm6', name: 'Lamb Biryani', category: 'mains', price_cents: 1550, tags: ['spicy'] },
  { id: 'm7', name: 'Samosa Chaat', category: 'starters', price_cents: 650, tags: ['vegetarian'], sold_out: true },
  { id: 'm8', name: 'Onion Bhaji', category: 'starters', price_cents: 550, tags: ['vegan', 'vegetarian'] },
  { id: 'm9', name: 'Gulab Jamun', category: 'desserts', price_cents: 500, tags: ['vegetarian', 'sweet'] },
  { id: 'm10', name: 'Mango Sorbet', category: 'desserts', price_cents: 450, tags: ['vegan', 'sweet'] },
  { id: 'm11', name: 'Mango Lassi', category: 'drinks', price_cents: 400, tags: ['vegetarian', 'drink'] },
  { id: 'm12', name: 'Masala Chai', category: 'drinks', price_cents: 300, tags: ['vegan', 'drink'] }
];
export const ALIASES = { 'paneer wrap': 'm1', 'paneer tikka wrap': 'm1', paneer: 'm1', 'shawarma wrap': 'm2', 'chicken shawarma': 'm2', shawarma: 'm2', 'chicken wrap': 'm2', 'falafel wrap': 'm3', falafel: 'm3', 'butter chicken': 'm4', 'chana masala': 'm5', chana: 'm5', biryani: 'm6', 'lamb biryani': 'm6', 'samosa chaat': 'm7', samosa: 'm7', samosas: 'm7', 'onion bhaji': 'm8', bhaji: 'm8', 'gulab jamun': 'm9', 'mango sorbet': 'm10', sorbet: 'm10', 'mango lassi': 'm11', 'mango lassis': 'm11', lassi: 'm11', lassis: 'm11', chai: 'm12', 'masala chai': 'm12' };
export const NUMS = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6 };

// Each Demo Bistro account has its own orders. The gateway passes the caller's token upstream,
// so Alice and Bob get different answers for the same question at the same MCP URL.
export function seedAccount(user) {
  const o = (id, status, label, eta, total, f) => ({ order_id: id, status, status_label: label, eta_minutes: eta, total_cents: total, total_formatted: money(total), fulfillment: f });
  if (user === 'bob') return { user, prefix: 'B', next: 2088, orders: { B2087: o('B2087', 'preparing', 'being prepared', 25, 1600, 'pickup') } };
  return { user, prefix: 'A', next: 1043, orders: { A1042: o('A1042', 'out_for_delivery', 'out for delivery', 8, 1900, 'delivery') } };
}
function apiSearchMenu(q) {
  const k = (q || '').toLowerCase().replace(/s$/, '');
  const items = MENU.filter((m) => !k || m.name.toLowerCase().includes(k) || m.tags.some((t) => t.includes(k)) || m.category.includes(k));
  return { status: 200, body: { count: items.length, items } };
}
function apiPlaceOrder(items, fulfillment, acct) {
  if (items.some((it) => it.item.sold_out)) return { status: 409, body: { error: 'sold_out' } };
  const sub = items.reduce((s, it) => s + it.item.price_cents * it.qty, 0), fee = fulfillment === 'delivery' ? 200 : 0;
  const id = acct.prefix + (acct.next++);
  const order = { order_id: id, status: 'received', status_label: 'received and waiting for the kitchen', fulfillment, total_cents: sub + fee, total_formatted: money(sub + fee), eta_minutes: fulfillment === 'delivery' ? 35 : 20 };
  acct.orders[id] = order; acct.last = id;
  return { status: 201, body: order };
}
function apiOrderStatus(acct, id) {
  const o = acct.orders[String(id || '').toUpperCase()];
  return o ? { status: 200, body: o } : { status: 404, body: { error: 'not_found' } };
}

/* ------------------------------------------------- response templating */
export function listNames(items) { const n = items.slice(0, 3).map((i) => i.name); return n.length > 1 ? n.slice(0, -1).join(', ') + ' and ' + n[n.length - 1] : (n[0] || ''); }
export function fill(tpl, body) {
  return tpl.replace(/\{(list|count):([\w.]+)\}/g, (m, fn, p) => {
    const arr = body[p.split('.')[0]] || [];
    return fn === 'count' ? arr.length : listNames(arr);
  }).replace(/\{(\w+)\}/g, (m, k) => (body[k] != null ? body[k] : m));
}

/* ------------------------------ tools/call as the gateway would answer it (C4)
   Returns what the simulator shows: { tool, arguments, request, status, text, data, is_error } */
function matchItem(name) { const k = String(name || '').toLowerCase().trim(); return MENU.find((m) => m.name.toLowerCase() === k) || MENU.find((m) => m.id === ALIASES[k]); }
export function callTool(name, args, acct) {
  const t = TOOLS.find((x) => x.name === name), base = t.http.baseUrl, a = {};
  Object.keys(args || {}).forEach((k) => { if (args[k] != null && args[k] !== '') a[k] = args[k]; });
  const res = (method, url, r, text) => ({ tool: name, arguments: a, request: { method, url }, status: r.status, text, data: r.body, is_error: r.status >= 400 });
  if (name === 'search_menu') {
    if (!a.query) return res('GET', base + '/menu/search', { status: 422, body: { error: 'query is required' } }, 'What should I search the menu for?');
    const r = apiSearchMenu(a.query);
    return res('GET', base + '/menu/search?query=' + encodeURIComponent(a.query), r, r.body.count ? fill(t.speakableResponse, r.body) : t.emptyResponse);
  }
  if (name === 'get_order_status') {
    if (!a.order_id) return res('GET', base + '/orders/{order_id}', { status: 422, body: { error: 'order_id is required' } }, 'Which order? Tell me the order ID, like A1042.');
    a.order_id = String(a.order_id).toUpperCase();
    const r = apiOrderStatus(acct, a.order_id);
    return res('GET', base + '/orders/' + encodeURIComponent(a.order_id), r, r.status === 404 ? t.errorResponses[404] : fill(t.speakableResponse, r.body));
  }
  if (name === 'place_order') {
    const wanted = (a.items || []).map((it) => ({ item: matchItem(it.item_name), qty: Math.max(1, Math.min(10, parseInt(it.quantity, 10) || 1)), asked: it.item_name }));
    a.items = wanted.map((w) => ({ item_name: w.item ? w.item.name : w.asked, quantity: w.qty }));
    a.fulfillment = a.fulfillment || 'delivery';
    const missing = wanted.find((w) => !w.item);
    if (!wanted.length || missing) return res('POST', base + '/orders', { status: 422, body: { error: 'unknown_item' } }, missing ? "I couldn't find " + missing.asked + ' on the Demo Bistro menu.' : 'Which dish would you like?');
    const r = apiPlaceOrder(wanted, a.fulfillment, acct);
    return res('POST', base + '/orders', r, r.status === 409 ? t.errorResponses[409] : fill(t.speakableResponse, r.body));
  }
}
