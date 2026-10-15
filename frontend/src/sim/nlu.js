// Scripted intent matching for the simulator's Ask mode (stands in for the LLM).
import { ALIASES, MENU, NUMS } from './demoBistro.js';

function parseOrder(text) {
  const t = text.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ');
  const fulfillment = /pick ?up|collect/.test(t) ? 'pickup' : 'delivery';
  const found = [];
  Object.keys(ALIASES).sort((a, b) => b.length - a.length).forEach((alias) => {
    const re = new RegExp('(?:(\\d+|a|an|one|two|three|four|five|six)\\s+)?' + alias.replace(/ /g, '\\s+') + '(s?)\\b');
    const m = t.match(re);
    if (m && !found.some((f) => f.id === ALIASES[alias])) found.push({ id: ALIASES[alias], qty: NUMS[m[1]] || 1 });
  });
  return { fulfillment, items: found.map((f) => { const m = MENU.find((x) => x.id === f.id); return { item_name: m.name, quantity: f.qty, price_cents: m.price_cents }; }) };
}
export function classify(text) {
  const t = text.toLowerCase();
  const orderId = (text.match(/\b([ab]\d{4})\b/i) || [])[1];
  if (/^(hi|hello|hey|good (morning|evening|afternoon))\b/.test(t)) return { intent: 'greet' };
  if (/\bcancel\b/.test(t)) return { intent: 'no_tool' };
  if (orderId || (/\b(where|when|status|arrive|track|eta|how long)\b/.test(t) && /\b(order|food|delivery)\b/.test(t))) return { intent: 'get_order_status', order_id: orderId };
  if (/\b(order|get me|i want|i'd like|i would like|send me|bring me|buy)\b/.test(t)) {
    const o = parseOrder(text);
    return Object.assign({ intent: 'place_order', empty: !o.items.length }, o);
  }
  if (/\b(menu|have|vegan|vegetarian|spicy|wraps?|desserts?|drinks?|starters?|mains?|dish(es)?|serve|offer|options)\b/.test(t) || /demo ?bistro/.test(t)) {
    const kw = ['vegan', 'vegetarian', 'spicy', 'wrap', 'dessert', 'drink', 'starter', 'main', 'paneer', 'chicken', 'lamb', 'mango', 'sweet'].find((k) => t.includes(k));
    return { intent: 'search_menu', query: kw || 'popular' };
  }
  return { intent: 'unknown' };
}
