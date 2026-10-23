import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useToast } from '../components/Toast.jsx';
import { MOCK } from '../lib/config.js';
import { sleep } from '../lib/utils.js';
import { useClient } from './clientState.jsx';

// Demo sign-in (C8): username only, returns a user token. The chips are the demo accounts from
// the API (GET /auth/demo-users); any other username signs in as a new user.
export default function Login() {
  const { backend, signIn, loadError } = useClient();
  const navigate = useNavigate();
  const toast = useToast();
  const accounts = backend.users();
  const [typed, setTyped] = useState(null);
  const username = typed ?? accounts[0]?.id ?? '';
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!username.trim()) { inputRef.current.focus(); return; }
    setBusy(true);
    let user;
    try {
      user = await backend.login(username);
    } catch (err) {
      user = null;
      setError(err.message);
    }
    if (!user) {
      setBusy(false);
      setError((e) => e || 'Use one of the demo accounts.');
      inputRef.current.focus();
      return;
    }
    if (MOCK) await sleep(500);
    signIn(user.id);
    navigate('/client', { replace: true });
    toast('Signed in as ' + user.name, 'ok', 2000);
  };

  return (
    <div className="app">
      <form className="login" onSubmit={submit}>
        <div className="brandline"><span className="orb lg"></span>alexa+</div>
        <h1>Who's using Alexa+?</h1>
        <div className="who-chips" role="group" aria-label="Demo users">
          {accounts.map((u) => (
            <button type="button" key={u.id} aria-pressed={username.trim().toLowerCase() === u.id} onClick={() => { setTyped(u.id); setError(null); }}>
              <span className="av" style={{ background: u.color }}>{u.name[0]}</span>{u.name}
            </button>
          ))}
        </div>
        <div className="field">
          <label htmlFor="un">Username</label>
          <input ref={inputRef} className="input" id="un" value={username} onChange={(e) => setTyped(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck="false" />
        </div>
        <div className="error" hidden={!(error || loadError)} style={{ color: 'var(--error)', fontSize: 13 }}>{error || loadError}</div>
        <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>{busy ? 'Signing in...' : 'Continue'}</button>
        <p className="small muted">
          Demo sign-in, no password. You get a user token, and every call to a service's MCP URL carries it so the gateway knows it's you.
        </p>
      </form>
    </div>
  );
}
