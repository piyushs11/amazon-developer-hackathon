// Answer templates a business writes in its manifest (x-alexa), same rules as the backend's
// assistant/speech.py:  {field}  {count:list}  {list:list.field}
const PLACEHOLDER = /\{(?:(count|list):)?([A-Za-z0-9_.]+)\}/g;

const get = (data, path) => path.split('.').reduce((d, k) => (d && typeof d === 'object' ? d[k] : undefined), data);

export const listNames = (items) => {
  const xs = items.filter((x) => x != null && x !== '').map(String);
  return xs.length > 1 ? xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1] : xs[0] || '';
};

export function render(template, data) {
  if (!template) return '';
  const text = template.replace(PLACEHOLDER, (_, fn, path) => {
    if (fn === 'count') { const v = get(data, path); return Array.isArray(v) ? String(v.length) : '0'; }
    if (fn === 'list') {
      const dot = path.lastIndexOf('.');
      const items = get(data, path.slice(0, dot));
      return Array.isArray(items) ? listNames(items.slice(0, 3).map((i) => (i && typeof i === 'object' ? i[path.slice(dot + 1)] : i))) : '';
    }
    const v = get(data, path);
    return v == null || typeof v === 'object' ? '' : String(v);
  });
  return text.replace(/\s{2,}/g, ' ').replace(/ \./g, '.').trim();
}

const firstList = (data) => Object.values(data || {}).find(Array.isArray);

// What Alexa says for one tool result, from that tool's profile (speakable/empty/error templates).
export function speak(toolProfile, data, { isError, status, fallback = '' }) {
  const tp = toolProfile || {};
  if (isError) return (status != null && tp.error_responses?.[String(status)]) || fallback || 'Something went wrong with that request.';
  const items = firstList(data);
  if (items && !items.length && tp.empty_response) return tp.empty_response;
  return render(tp.speakable_response, data) || fallback;
}

// Fill a confirmation prompt like "Should I order {quantity} × {item}?" (no lists).
export const fill = (template, values) => render(template, values || {});
