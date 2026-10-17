import { createContext, useCallback, useContext, useState } from 'react';
import { MANIFEST } from '../data/manifest.js';
import { checkReport } from '../data/checks.js';
import { daysAgo } from '../lib/utils.js';

const PUB = MANIFEST.publisher;

export const STATUS = {
  rejected: { cls: 'err', label: 'Rejected' },
  in_review: { cls: 'prog', label: 'In review' },
  approved: { cls: 'ok', label: 'Approved' },
  live: { cls: 'live', label: 'Live' },
  submitted: { cls: 'info', label: 'Submitted' },
};

export function bump(v) {
  const p = v.split('.');
  p[p.length - 1] = String((parseInt(p[p.length - 1], 10) || 0) + 1);
  return p.join('.');
}

// Demo Bistro starts with version 0.9 rejected (the reviewer's test account did not sign in).
const initialSubmissions = () => [{
  version: '0.9', status: 'rejected', submitted: daysAgo(10, 14, 12), reviewed: daysAgo(8, 10, 40), report: checkReport(),
  message: 'Initial submission',
  reason: "We couldn't sign in with the test account in private.testAccount (auth.demobistro.test returned invalid credentials), so place_order and get_order_status couldn't be verified. Update the test account and submit a new version.",
}];

const initialWizard = () => ({ file: null, pdf: null, done: false, version: '1.0', message: '', confirm: false });

const OwnerContext = createContext(null);
export const useOwner = () => useContext(OwnerContext);

// In-memory demo state for the Owner Portal (reloading the page resets it, like the prototype).
// Replace the setters with API calls when the backend exists.
export function OwnerProvider({ children }) {
  const owner = { name: PUB.name, email: PUB.contactEmail, domain: PUB.domain };
  const [submissions, setSubmissions] = useState(initialSubmissions);
  const [wizard, setWizard] = useState(initialWizard);

  const patchWizard = useCallback((patch) => setWizard((w) => ({ ...w, ...patch })), []);

  // Adds the new version as "in review". Returns the submitted version.
  // The wizard is only flagged here; it resets itself the next time it opens (resetWizard), so
  // nothing changes underneath the step that is still on screen while navigation happens.
  const submit = useCallback(() => {
    const version = wizard.version.trim() || '1.0';
    setSubmissions((list) => [{
      version, status: 'in_review', submitted: new Date(), report: checkReport(), message: wizard.message, pdf: wizard.pdf,
    }, ...list]);
    setWizard((w) => ({ ...w, submitted: true, nextVersion: bump(version) }));
    return version;
  }, [wizard]);

  const resetWizard = useCallback(
    () => setWizard((w) => ({ ...initialWizard(), version: w.nextVersion || w.version })),
    []
  );

  const latest = submissions[0];
  return (
    <OwnerContext.Provider value={{ owner, submissions, latest, wizard, patchWizard, submit, resetWizard }}>
      {children}
    </OwnerContext.Provider>
  );
}

export function StatusLabel({ status, big }) {
  const s = STATUS[status];
  return <span className={'status ' + s.cls + (big ? ' lg' : '')}>{s.label}</span>;
}
