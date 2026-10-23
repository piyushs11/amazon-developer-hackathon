import { useEffect, useRef, useState } from 'react';
import { useOverlay } from '../components/Overlay.jsx';
import { useToast } from '../components/Toast.jsx';
import { MOCK } from '../lib/config.js';
import Icon from '../lib/Icon.jsx';
import { sleep } from '../lib/utils.js';
import { OAUTH_CHANNEL } from './ConnectDone.jsx';
import { useClient } from './clientState.jsx';
import { ConnectErrorSheet } from './sheets.jsx';

export default function OAuthWindow({ uuid }) {
  return MOCK ? <MockOAuthWindow uuid={uuid} /> : <RealOAuthWindow uuid={uuid} />;
}

// GET /oauth/start gives the service's own sign-in page. It opens in a popup; /oauth/callback
// stores the token and sends the popup to /connect/done, which tells this window over a
// BroadcastChannel and closes. If the popup is blocked, the user can retry or use this tab.
function RealOAuthWindow({ uuid }) {
  const { backend, me, closeLayer, openPublish } = useClient();
  const overlay = useOverlay();
  const toast = useToast();
  const s = backend.catalog[uuid];
  const [phase, setPhase] = useState('opening'); // opening | waiting | blocked | finishing
  const popup = useRef(null);
  const started = useRef(false);
  const done = useRef(false);
  const wasExpired = useRef(backend.link(me.id, uuid)?.status === 'expired');

  const fail = (why) => {
    if (done.current) return;
    done.current = true;
    try { popup.current?.close(); } catch { /* already gone */ }
    closeLayer();
    overlay.open(<ConnectErrorSheet uuid={uuid} reason={why} />, { sheet: true });
  };

  const finish = async (status) => {
    if (done.current) return;
    if (status !== 'ok') { fail(s.name + " didn't allow access."); return; }
    done.current = true;
    try { popup.current?.close(); } catch { /* already gone */ }
    setPhase('finishing');
    try {
      await Promise.all([backend.refresh(me.id), backend.loadService(uuid)]);
    } catch (e) {
      toast(e.message, 'err');
    }
    if (wasExpired.current) {
      closeLayer();
      toast(s.name + ' reconnected. Its new token is stored.', 'ok');
    } else {
      openPublish(uuid);
    }
  };

  // Has to run right after the user's click, or the browser blocks the popup.
  const open = async () => {
    const win = window.open('', 'mcpb-oauth', 'popup,width=480,height=680');
    if (!win) { setPhase('blocked'); return; }
    popup.current = win;
    setPhase('waiting');
    try {
      win.location.href = await backend.startOAuth(me.id, uuid);
    } catch (e) {
      fail(e.message);
    }
  };

  // No popup: sign in in this tab. /connect/done brings the user back to Services afterwards.
  const useThisTab = async () => {
    try {
      window.location.href = await backend.startOAuth(me.id, uuid);
    } catch (e) {
      fail(e.message);
    }
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    open();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let channel = null;
    try {
      channel = new BroadcastChannel(OAUTH_CHANNEL);
      channel.onmessage = (e) => finish(e.data?.status);
    } catch { /* no BroadcastChannel: the closed-window check below still ends the wait */ }
    // The user closed the popup without finishing. Give a message sent just before a moment to arrive.
    let closedAt = null;
    const timer = setInterval(() => {
      if (!popup.current?.closed || done.current) return;
      closedAt = closedAt || Date.now();
      if (Date.now() - closedAt > 1500) fail('You closed the ' + s.name + ' window before finishing.');
    }, 400);
    return () => { clearInterval(timer); channel?.close(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="full">
      <div className="inner">
        <div className="app-top">
          <button type="button" className="btn-icon btn" aria-label="Close" onClick={() => fail('You cancelled before signing in to ' + s.name + '.')}><Icon name="x" /></button>
          <div className="title">Connect {s.name}</div>
          <span style={{ width: 38 }}></span>
        </div>
        <div className="app-body">
          <div className="not-avail">
            <div className="ring" style={{ background: 'var(--blue-tint)', color: 'var(--blue)' }}><Icon name={phase === 'blocked' ? 'alert' : 'lock'} /></div>
            {phase === 'blocked' ? (
              <>
                <h2>Your browser blocked the sign-in window</h2>
                <p className="muted">Open it again, or sign in to {s.name} in this tab.</p>
                <div className="stack-s" style={{ marginTop: 10, width: '100%' }}>
                  <button type="button" className="btn btn-primary btn-lg btn-block" onClick={open}>Open {s.domain || s.name} sign-in</button>
                  <button type="button" className="btn btn-secondary btn-lg btn-block" onClick={useThisTab}>Use this tab instead</button>
                </div>
              </>
            ) : phase === 'finishing' ? (
              <>
                <h2>Returning to MCP Bridge...</h2>
                <p className="muted">Account connected.</p>
              </>
            ) : (
              <>
                <h2>Sign in to {s.name}</h2>
                <p className="muted">Finish in the {s.domain || s.name} window. We never see your password.</p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// The prototype's simulated sign-in window (VITE_MOCK=1): sign in, allow access, return.
function MockOAuthWindow({ uuid }) {
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
