import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useToast } from '../components/Toast.jsx';
import { sleep } from '../lib/utils.js';
import { useClient } from './clientState.jsx';

// Demo sign-in (C8): username only, returns a user token.
export default function Login() {
  const { backend, signIn } = useClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [username, setUsername] = useState('alice');
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef(null);

  const submit = async (e) => {
    e.preventDefault();
    const user = backend.login(username);
    if (!user) { setError(true); inputRef.current.focus(); return; }
    setBusy(true);
    await sleep(500);
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
          {backend.users().map((u) => (
            <button type="button" key={u.id} aria-pressed={username.trim().toLowerCase() === u.id} onClick={() => { setUsername(u.id); setError(false); }}>
              <span className="av" style={{ background: u.color }}>{u.name[0]}</span>{u.name}
            </button>
          ))}
        </div>
        <div className="field">
          <label htmlFor="un">Username</label>
          <input ref={inputRef} className="input" id="un" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck="false" />
        </div>
        <div className="error" hidden={!error} style={{ color: 'var(--error)', fontSize: 13 }}>Use alice or bob.</div>
        <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>{busy ? 'Signing in...' : 'Continue'}</button>
        <p className="small muted">Demo sign-in, no password. You get a user token, and every call to a service's MCP URL carries it so the gateway knows it's you.</p>
      </form>
    </div>
  );
}
