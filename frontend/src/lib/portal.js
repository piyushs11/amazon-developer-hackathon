// Shared by the Owner Portal and the Review Console: adapters from the API's submission data to
// what the existing components (ToolCard, ChecksList) display.

// A tool from the API's check report (backend submissions/manifest.py tools_from_manifest).
export function toToolCard(t, baseUrl = '') {
  const se = t.side_effect || (t.read_only ? 'none' : 'write');
  return {
    name: t.name, title: t.title, description: t.description,
    http: { method: t.method, path: t.path, baseUrl },
    read_only: t.read_only,
    params: (t.params || []).map((p) => ({ ...p, type: p.enum ? p.enum.join(' | ') : p.type })),
    annotations: { readOnlyHint: se === 'none', destructiveHint: se !== 'none', idempotentHint: se === 'none', openWorldHint: true },
    sideEffect: se, requiresConfirmation: !!t.requires_confirmation, confirmationPrompt: t.confirmation_prompt,
    speakableResponse: t.speakable_response, emptyResponse: t.empty_response,
    errorResponses: t.error_responses || {}, examplePhrases: t.example_phrases || [],
    exampleArgs: t.example_args || {},
  };
}

export const apiBase = (manifest) => manifest?.openapi?.servers?.[0]?.url || '';

export const toolCards = (report, manifest) => (report?.tools || []).map((t) => toToolCard(t, apiBase(manifest)));

// "3 of 8 passed · 5 warnings" style counts for a check report.
export function checkCounts(report) {
  const checks = report?.checks || [];
  const count = (s) => checks.filter((c) => c.status === s).length;
  return { total: checks.length, ok: count('ok'), warn: count('warn'), err: count('err') };
}

export function checksLabel(report) {
  const c = checkCounts(report);
  if (c.err) return { cls: 'err', text: c.err + ' failed' };
  if (c.warn) return { cls: 'warn', text: c.ok + ' passed · ' + c.warn + ' warning' + (c.warn > 1 ? 's' : '') };
  return { cls: 'ok', text: c.total + ' of ' + c.total + ' passed' };
}

// The public copy hosted at /.well-known: the manifest without its private block.
export const hostedCopy = (manifest) => {
  const m = JSON.parse(JSON.stringify(manifest || {}));
  delete m.private;
  return m;
};

export const writeSummary = (tools) => {
  const writes = tools.filter((t) => !t.read_only).length;
  return tools.length + ' · ' + writes + ' write, ' + (tools.length - writes) + ' read';
};

export const toDate = (s) => (s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z') : null);

// File -> base64 (for the PDF attachment upload).
export const fileToBase64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(',')[1] || '');
  r.onerror = () => reject(r.error);
  r.readAsDataURL(file);
});
