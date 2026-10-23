import { createContext, useContext, useEffect, useState } from 'react';
import { demoLogin, demoUsers, session } from '../lib/api.js';

// Sign-in for the Owner Portal and the Review Console: pick a seeded account of the right role
// (GET /auth/demo-users?role=...). The API checks the role on every call; this only remembers
// who is signed in for this browser tab.
const PortalContext = createContext(null);
export const usePortal = () => useContext(PortalContext);

const read = (key) => { try { return sessionStorage.getItem(key); } catch { return null; } };
const write = (key, value) => {
  try { if (value) sessionStorage.setItem(key, value); else sessionStorage.removeItem(key); } catch { /* blocked */ }
};

export default function PortalGate({ role, storageKey, title, lede, children }) {
  const [sess, setSess] = useState(null);
  const [restoring, setRestoring] = useState(() => !!read(storageKey));
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const signIn = async (username) => {
    setBusy(true);
    setError(null);
    try {
      const profile = await demoLogin(username);
      if (profile.role !== role) throw new Error(`${profile.display_name} isn't a${role === 'owner' ? 'n owner' : ' reviewer'} account.`);
      write(storageKey, profile.user_id);
      setSess(session(profile));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    demoUsers(role).then(setAccounts).catch((e) => setError(e.message));
    const saved = read(storageKey);
    if (saved) {
      demoLogin(saved)
        .then((p) => { if (p.role === role) setSess(session(p)); else write(storageKey, null); })
        .catch(() => write(storageKey, null))
        .finally(() => setRestoring(false));
    }
  }, [role, storageKey]);

  const signOut = () => { write(storageKey, null); setSess(null); };

  if (restoring) return null;
  if (!sess) {
    return (
      <div className="portal-gate">
        <div className="card stack" style={{ maxWidth: 440, margin: '12vh auto', padding: 28 }}>
          <div>
            <h1 style={{ fontSize: 24, marginBottom: 6 }}>{title}</h1>
            <p className="muted">{lede}</p>
          </div>
          <div className="stack-s">
            {accounts.map((a) => (
              <button key={a.user_id} type="button" className="btn btn-secondary btn-lg btn-block" disabled={busy}
                style={{ justifyContent: 'flex-start', gap: 12 }} onClick={() => signIn(a.user_id)}>
                <span className="avatar" style={{ background: a.color, width: 30, height: 30, fontSize: 13 }}>{a.display_name[0]}</span>
                <span style={{ textAlign: 'left' }}>{a.display_name}<span className="small muted" style={{ display: 'block' }}>{a.email}</span></span>
              </button>
            ))}
            {!accounts.length && !error && <p className="muted">Loading accounts...</p>}
          </div>
          {error && <div className="banner err"><div>{error}</div></div>}
          <p className="small muted">Demo sign-in, no password. The accounts come from the database seed.</p>
        </div>
      </div>
    );
  }
  return <PortalContext.Provider value={{ sess, profile: sess.profile, signOut }}>{children}</PortalContext.Provider>;
}
