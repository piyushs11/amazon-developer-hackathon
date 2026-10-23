import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { usePortal } from '../components/PortalGate.jsx';
import { checksLabel, toDate, toolCards } from '../lib/portal.js';

// Review Console state, from the API (/api/review/*): the queue, each submission's details, the
// catalog, and the reviewer's decisions.
export const STATUS = {
  pending: { cls: 'info', label: 'Pending review' },
  in_review: { cls: 'prog', label: 'In review' },
  approved: { cls: 'ok', label: 'Approved' },
  rejected: { cls: 'err', label: 'Rejected' },
};

const ReviewContext = createContext(null);
export const useReview = () => useContext(ReviewContext);

export const isOpen = (s) => s.status === 'pending' || s.status === 'in_review';

// API submission -> what the screens show. Details (manifest, history, live) are filled in once
// the submission has been opened.
export function normalize(x) {
  const m = x.manifest || null;
  return {
    id: String(x.id), raw: x, service: x.service_name, domain: x.domain, uuid: x.service_uuid,
    category: x.category, city: x.city, version: x.version, status: x.status,
    submitted: toDate(x.submitted_at), reviewed: toDate(x.reviewed_at),
    assignee: x.assignee, reviewer: x.reviewer, reason: x.reason, note: x.note, message: x.message,
    description: x.description, pdf: x.attachment_name, owner: x.owner, checks: x.checks,
    contact: m?.publisher?.contactEmail || x.owner?.email || '',
    report: x.check_report || null, manifest: m,
    tools: x.check_report ? toolCards(x.check_report, m) : null,
    linking: m?.accountLinking || null, testAccount: m?.private?.testAccount || null, reviewNotes: m?.private?.reviewNotes || '',
    history: (x.history || []).map((h) => ({ ...h, submitted: toDate(h.submitted_at), reviewed: toDate(h.reviewed_at) })),
    live: x.live ? { ...x.live, published_at: toDate(x.live.published_at) } : null,
    loaded: !!m,
  };
}

export function ReviewProvider({ children }) {
  const { sess, profile, signOut } = usePortal();
  const [subs, setSubs] = useState(null);
  const [details, setDetails] = useState({});
  const [filter, setFilter] = useState('open');
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    try {
      setSubs((await sess.get('/api/review/submissions')).map(normalize));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, [sess]);
  useEffect(() => {
    let live = true;
    sess.get('/api/review/submissions')
      .then((list) => { if (live) setSubs(list.map(normalize)); })
      .catch((e) => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [sess]);

  const store = useCallback((row) => {
    const s = normalize(row);
    setDetails((all) => ({ ...all, [s.id]: s }));
    setSubs((list) => (list ? list.map((x) => (x.id === s.id ? { ...x, ...s, loaded: x.loaded || s.loaded } : x)) : list));
    return s;
  }, []);

  const loadDetail = useCallback(async (id) => store(await sess.get('/api/review/submissions/' + id)), [sess, store]);

  const value = useMemo(() => ({
    reviewer: { id: profile.user_id, name: profile.display_name, email: profile.email,
      initials: profile.display_name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase() },
    sess, signOut, subs: subs || [], loading: subs === null, error, filter, setFilter, refresh,
    detail: (id) => details[id],
    loadDetail,
    startReview: async (id) => store(await sess.post(`/api/review/submissions/${id}/start`)),
    approve: async (id, note) => { const s = store(await sess.post(`/api/review/submissions/${id}/approve`, { note })); await refresh(); return s; },
    reject: async (id, reason) => { const s = store(await sess.post(`/api/review/submissions/${id}/reject`, { reason })); await refresh(); return s; },
    tryTool: (id, tool, args) => sess.post(`/api/review/submissions/${id}/try`, { tool, arguments: args }),
    catalog: () => sess.get('/api/review/catalog'),
  }), [profile, sess, signOut, subs, error, filter, refresh, details, loadDetail, store]);

  return <ReviewContext.Provider value={value}>{children}</ReviewContext.Provider>;
}

export function StatusLabel({ status, big }) {
  const s = STATUS[status] || { cls: '', label: status };
  return <span className={'status ' + s.cls + (big ? ' lg' : '')}>{s.label}</span>;
}

// From a full report, or from the counts a queue row carries.
export function ChecksSummary({ report, checks }) {
  if (report) {
    const l = checksLabel(report);
    return <span className={'status ' + l.cls}>{l.text}</span>;
  }
  if (!checks) return null;
  if (checks.err) return <span className="status err">{checks.err} failed</span>;
  if (checks.warn) return <span className="status warn">{checks.ok} passed · {checks.warn} warning{checks.warn > 1 ? 's' : ''}</span>;
  return <span className="status ok">{checks.total} of {checks.total} passed</span>;
}
