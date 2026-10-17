import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { seedAccount } from '../sim/demoBistro.js';
import { STATUS, seedSubmissions } from './reviewData.js';

const ReviewContext = createContext(null);
export const useReview = () => useContext(ReviewContext);

export const isOpen = (s) => s.status === 'pending' || s.status === 'in_review';
const ME = 'J. Rivera';

// In-memory review queue. Swap the actions for API calls when the review backend exists.
export function ReviewProvider({ children }) {
  const [subs, setSubs] = useState(seedSubmissions);
  const [filter, setFilter] = useState('open');
  // The simulator's test account keeps its orders between visits to the Try it tab.
  const [reviewerAcct] = useState(() => seedAccount('reviewer'));

  const update = useCallback((id, patch) => {
    setSubs((list) => list.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }, []);

  const value = useMemo(() => ({
    subs,
    filter,
    setFilter,
    reviewerAcct,
    find: (id) => subs.find((s) => s.id === id),
    startReview: (id) => update(id, { status: 'in_review', assignee: ME }),
    approve: (id, note) => update(id, { status: 'approved', reviewed: new Date(), reviewer: ME, note, assignee: undefined }),
    reject: (id, reason) => update(id, { status: 'rejected', reviewed: new Date(), reviewer: ME, reason, assignee: undefined }),
  }), [subs, filter, reviewerAcct, update]);

  return <ReviewContext.Provider value={value}>{children}</ReviewContext.Provider>;
}

export function StatusLabel({ status, big }) {
  const s = STATUS[status];
  return <span className={'status ' + s.cls + (big ? ' lg' : '')}>{s.label}</span>;
}

export function ChecksSummary({ report }) {
  const warn = report.checks.filter((c) => c.status === 'warn').length;
  const err = report.checks.filter((c) => c.status === 'err').length;
  if (err) return <span className="status err">{err} failed</span>;
  if (warn) return <span className="status warn">{8 - warn} passed · {warn} warning</span>;
  return <span className="status ok">8 of 8 passed</span>;
}
