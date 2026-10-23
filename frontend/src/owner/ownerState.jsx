import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { usePortal } from '../components/PortalGate.jsx';
import { fileToBase64, toDate } from '../lib/portal.js';

// Owner Portal state, from the API (/api/owner/*): the signed-in owner's connectors, each
// connector's latest submission, and the submission wizard in progress.
export const STATUS = {
  pending: { cls: 'info', label: 'Waiting for review' },
  in_review: { cls: 'prog', label: 'In review' },
  approved: { cls: 'ok', label: 'Approved' },
  rejected: { cls: 'err', label: 'Rejected' },
  live: { cls: 'live', label: 'Live' },
  draft: { cls: '', label: 'Draft' },
};

export function bump(v) {
  const p = String(v || '1.0').split('.');
  p[p.length - 1] = String((parseInt(p[p.length - 1], 10) || 0) + 1);
  return p.join('.');
}

const initialWizard = (target = null) => ({ target, file: null, pdf: null, report: null, version: '', message: '', confirm: false });

// Dates arrive as ISO strings; the screens format Date objects.
const withDates = (s) => s && ({ ...s, submitted: toDate(s.submitted_at), reviewed: toDate(s.reviewed_at) });
const normConnector = (c) => c && ({
  ...c,
  submissions: (c.submissions || []).map(withDates),
  latest: c.latest ? { ...withDates(c.latest), history: (c.latest.history || []).map(withDates) } : c.latest,
});

const OwnerContext = createContext(null);
export const useOwner = () => useContext(OwnerContext);

export function OwnerProvider({ children }) {
  const { sess, profile, signOut } = usePortal();
  const owner = {
    id: profile.user_id, name: profile.display_name, email: profile.email, color: profile.color,
    initials: profile.display_name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase(),
  };
  const [connectors, setConnectors] = useState(null);
  const [details, setDetails] = useState({});
  const [error, setError] = useState(null);
  const [wizard, setWizard] = useState(initialWizard);

  const refresh = useCallback(async () => {
    try {
      setConnectors((await sess.get('/api/owner/connectors')).map(normConnector));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [sess]);
  useEffect(() => {
    let live = true;
    sess.get('/api/owner/connectors')
      .then((list) => { if (live) setConnectors(list.map(normConnector)); })
      .catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [sess]);

  const loadConnector = useCallback(async (uuid) => {
    const d = normConnector(await sess.get('/api/owner/connectors/' + encodeURIComponent(uuid)));
    setDetails((all) => ({ ...all, [uuid]: d }));
    return d;
  }, [sess]);

  const patchWizard = useCallback((patch) => setWizard((w) => ({ ...w, ...patch })), []);
  const resetWizard = useCallback((target = null) => setWizard(initialWizard(target)), []);

  // POST /api/owner/checks: the 8 automated checks on the uploaded manifest (nothing stored).
  const runChecks = useCallback((manifest) => sess.post('/api/owner/checks', { manifest }), [sess]);

  // POST /api/owner/submissions. `version` (the wizard's field) wins over openapi.info.version.
  const submit = useCallback(async (version) => {
    const manifest = JSON.parse(JSON.stringify(wizard.file.manifest));
    if (version?.trim()) {
      manifest.openapi = { ...manifest.openapi, info: { ...(manifest.openapi?.info || {}), version: version.trim() } };
    }
    let attachment = null;
    if (wizard.pdf?.file) attachment = { name: wizard.pdf.name, content_base64: await fileToBase64(wizard.pdf.file) };
    const row = withDates(await sess.post('/api/owner/submissions', { manifest, message: wizard.message, attachment }));
    setWizard((w) => ({ ...w, submitted: true }));
    await refresh();
    await loadConnector(row.service_uuid).catch(() => {});
    return row;
  }, [sess, wizard, refresh, loadConnector]);

  return (
    <OwnerContext.Provider value={{
      owner, sess, signOut, connectors, error, refresh, details, loadConnector,
      wizard, patchWizard, resetWizard, runChecks, submit,
    }}>
      {children}
    </OwnerContext.Provider>
  );
}

// The connector for a route param, loading its details if needed. null while loading.
export function useConnector(uuid) {
  const { details, loadConnector } = useOwner();
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    if (!uuid || details[uuid]) return;
    loadConnector(uuid).catch(() => setMissing(true));
  }, [uuid, details, loadConnector]);
  return { connector: details[uuid] || null, missing };
}

export function StatusLabel({ status, big }) {
  const s = STATUS[status] || { cls: '', label: status };
  return <span className={'status ' + s.cls + (big ? ' lg' : '')}>{s.label}</span>;
}
