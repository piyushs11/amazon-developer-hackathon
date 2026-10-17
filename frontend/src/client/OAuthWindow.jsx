import { useEffect, useRef, useState } from 'react';
import { useOverlay } from '../components/Overlay.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { sleep } from '../lib/utils.js';
import { useClient } from './clientState.jsx';
import { ConnectErrorSheet } from './sheets.jsx';

// GET /oauth/start opens the service's own login page; /oauth/callback brings the user back.
// This simulates that window: sign in, allow access, then return to MCP Bridge.
export default function OAuthWindow({ uuid }) {
  const { backend, me, closeLayer, openPublish } = useClient();
  const overlay = useOverlay();
  const toast = useToast();
  const s = backend.catalog[uuid];
  const [step, setStep] = useState('login'); // login | consent | returning
  const [email, setEmail] = useState(me.email);
  const [password, setPassword] = useState('');
  const [pwError, setPwError] = useState(false);
  const [busy, setBusy] = useState(false);
  const pwRef = useRef(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const fail = (why) => {
    closeLayer();
    overlay.open(<ConnectErrorSheet uuid={uuid} reason={why} />, { sheet: true });
  };

  const onClose = () => {
    if (step === 'login') fail('You closed the ' + s.name + ' window before finishing.');
    else if (step === 'consent') fail('You closed the ' + s.name + ' window before allowing access.');
  };

  const signIn = async (e) => {
    e.preventDefault();
    if (!password.trim()) { setPwError(true); pwRef.current.focus(); return; }
    setBusy(true);
    await sleep(800);
    if (!mounted.current) return;
    setBusy(false);
    setStep('consent');
  };

  const allow = async () => {
    setBusy(true);
    await sleep(500);
    if (!mounted.current) return;
    setStep('returning');
    await sleep(700);
    if (!mounted.current) return;
    const { reconnected } = backend.completeOAuth(me.id, uuid);
    if (reconnected) {
      closeLayer();
      toast(s.name + ' reconnected. Its new token is stored.', 'ok');
    } else {
      openPublish(uuid);
    }
  };

  const brand = (
    <div className="tb-logo" style={{ color: s.color }}>
      <span className="mk" style={{ background: s.color }}><Icon name={s.glyph} /></span>{s.name}
    </div>
  );

  return (
    <div className="full">
      <div className="inner">
        <div className="browser" style={{ border: 0, borderRadius: 0, flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div className="bar">
            <button type="button" className="done" onClick={onClose}>Close</button>
            <div className="url"><Icon name="lock" cls="s" /><b>{step === 'returning' ? 'mcpbridge.dev/connect/done?status=ok' : s.authHost + '/authorize'}</b></div>
            <span style={{ width: 40 }}></span>
          </div>
          <div className="page grow" style={{ overflow: 'auto' }}>
            {step === 'login' && (
              <>
                {brand}
                <h2 style={{ margin: '22px 0 4px', fontSize: 22 }}>Sign in</h2>
                <p className="muted" style={{ marginBottom: 18 }}>to connect with MCP Bridge for Alexa+</p>
                <form className="stack" onSubmit={signIn}>
                  <div className="field"><label htmlFor="em">Email</label><input className="tb-input" id="em" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></div>
                  <div className="field"><label htmlFor="pw">Password</label><input ref={pwRef} className="tb-input" id="pw" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={'Your ' + s.name + ' password'} autoComplete="current-password" /></div>
                  <div className="error" hidden={!pwError} style={{ color: 'var(--error)', fontSize: 13 }}>Enter your password.</div>
                  <button className="tb-btn" type="submit" style={{ background: s.color }} disabled={busy}>{busy ? 'Signing in...' : 'Sign in'}</button>
                </form>
                <p className="muted small" style={{ marginTop: 16, textAlign: 'center' }}>This is {s.name}'s page. MCP Bridge doesn't see what you type here.</p>
              </>
            )}
            {step === 'consent' && (
              <>
                {brand}
                <h2 style={{ margin: '22px 0 6px', fontSize: 22 }}>Allow MCP Bridge?</h2>
                <p className="muted" style={{ marginBottom: 16 }}>Signed in as <b>{me.email}</b>. MCP Bridge will be able to:</p>
                <ul className="consent-list">{s.scopes.map((sc) => <li key={sc}><Icon name="check" cls="s" /><span>{sc}</span></li>)}</ul>
                <div className="stack-s">
                  <button className="tb-btn" style={{ background: s.color }} disabled={busy} onClick={allow}>{busy ? 'Connecting...' : 'Allow'}</button>
                  <button className="btn btn-outline btn-lg btn-block" style={{ borderRadius: 8 }} onClick={() => fail('You chose Cancel on ' + s.domain + '.')}>Cancel</button>
                </div>
              </>
            )}
            {step === 'returning' && (
              <div className="not-avail">
                <div className="ring" style={{ background: 'var(--blue-tint)', color: 'var(--blue)' }}><Icon name="arrow-left" /></div>
                <h2>Returning to MCP Bridge...</h2>
                <p className="muted">Account connected.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
