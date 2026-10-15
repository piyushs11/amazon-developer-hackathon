// Small helpers shared by all three portals (from the prototype's shared script).
export const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const money = (cents) => '$' + (cents / 100).toFixed(2);
export function fmtTime(d) { return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
export function fmtDate(d) { return d.toLocaleDateString([], { month: 'short', day: 'numeric' }); }
export function fmtDateTime(d) { return fmtDate(d) + ' at ' + fmtTime(d); }
export function daysAgo(n, h, m) { const d = new Date(); d.setDate(d.getDate() - n); if (h != null) d.setHours(h, m || 0, 0, 0); return d; }
export function humanize(op) { return op.replace(/([A-Z])/g, ' $1').replace(/^./, (c) => c.toUpperCase()).trim(); }
