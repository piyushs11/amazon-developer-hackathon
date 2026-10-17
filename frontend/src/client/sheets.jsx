import CopyButton from '../components/CopyButton.jsx';
import { useOverlay } from '../components/Overlay.jsx';
import Switch from '../components/Switch.jsx';
import { useToast } from '../components/Toast.jsx';
import { mcpUrl } from '../data/manifest.js';
import Icon from '../lib/Icon.jsx';
import { fmtDate, fmtTime } from '../lib/utils.js';
import { useClient } from './clientState.jsx';
import { SheetLogo, ToolList } from './bits.jsx';

// S2b: what connecting means, before the service's own sign-in page opens.
export function ConnectSheet({ uuid }) {
  const { backend, openOAuth } = useClient();
  const overlay = useOverlay();
  const s = backend.catalog[uuid];
  return (
    <>
      <h2>Connect {s.name}</h2>
      <p className="muted" style={{ fontSize: 15, marginBottom: 14 }}>You'll sign in on {s.domain} in a new window, then come straight back here.</p>
      <div className="consent-head"><span className="orb lg"></span><span className="lk"><Icon name="link" /></span><span className="lgo" style={{ background: s.color }}>{s.initials}</span></div>
      <div className="never"><Icon name="lock" cls="s" /><span><b>We never see your password.</b> {s.name} gives us a token instead.</span></div>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>Tools</div>
      <ToolList tools={s.tools} />
      <div className="actions">
        <button type="button" className="btn btn-primary btn-lg" onClick={() => { overlay.close(); openOAuth(uuid); }}>Continue to {s.domain}</button>
        <button type="button" className="btn btn-secondary btn-lg" onClick={overlay.close}>Cancel</button>
      </div>
    </>
  );
}

export function ConnectErrorSheet({ uuid, reason }) {
  const { backend, openOAuth } = useClient();
  const overlay = useOverlay();
  const s = backend.catalog[uuid];
  return (
    <>
      <div className="not-avail" style={{ padding: '8px 0 0' }}>
        <div className="ring" style={{ background: 'var(--error-bg)', color: 'var(--error)' }}><Icon name="alert" /></div>
        <h2 style={{ marginTop: 6 }}>Couldn't connect {s.name}</h2>
        <p className="muted" style={{ fontSize: 15 }}>{reason} Nothing was saved.</p>
      </div>
      <div className="actions">
        <button type="button" className="btn btn-primary btn-lg" onClick={() => { overlay.close(); openOAuth(uuid); }}>Try again</button>
        <button type="button" className="btn btn-secondary btn-lg" onClick={overlay.close}>Not now</button>
      </div>
    </>
  );
}

export function ManageSheet({ uuid }) {
  const { backend, me, rowAction } = useClient();
  const overlay = useOverlay();
  const s = backend.catalog[uuid];
  const l = backend.link(me.id, uuid);
  if (!l) return null;
  const st = backend.statusOf(me.id, uuid);
  const live = backend.isPublished(uuid);
  const act = () => { overlay.close(); rowAction(uuid); };

  return (
    <>
      <div className="app-sheet-head">
        <SheetLogo s={s} />
        <div><h2 style={{ margin: 0 }}>{s.name}</h2><div className="muted small">Connected as {l.account} · {fmtDate(l.since)}</div></div>
      </div>
      {l.status === 'active' && (
        <div className="list-row" style={{ padding: '14px 0' }}>
          <span>Use with Alexa+</span>
          <Switch on={l.on} onChange={(on) => backend.setEnabled(me.id, uuid, on)} style={{ marginLeft: 'auto' }} />
        </div>
      )}
      <div className="list-row" style={{ padding: '14px 0' }}><span>Status</span><span className={'status ' + st.cls} style={{ marginLeft: 'auto' }}>{st.label}</span></div>
      <div className="list-row" style={{ padding: '14px 0' }}>
        <span>Last called</span>
        <span className="muted" style={{ marginLeft: 'auto', fontSize: 14 }}>{l.lastCalled ? fmtDate(l.lastCalled) + ' at ' + fmtTime(l.lastCalled) : 'Not yet'}</span>
      </div>
      <div className="list-row" style={{ padding: '12px 0', alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <span>MCP URL</span>
        {live ? (
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center', minWidth: 0 }}>
            <span className="mcp" style={{ margin: 0 }}>{mcpUrl(uuid)}</span>
            <CopyButton value={mcpUrl(uuid)} label="Copy MCP URL" />
          </span>
        ) : (
          <span className="muted" style={{ marginLeft: 'auto', fontSize: 14 }}>After the first publish</span>
        )}
      </div>
      {l.status === 'expired' && (
        <div className="banner err" style={{ marginTop: 12 }}><Icon name="alert" /><div>Your {s.name} sign-in expired and couldn't be refreshed. Reconnect to keep using it.</div></div>
      )}
      <div className="perm" style={{ border: 0, paddingTop: 16 }}>
        <span className="ic"><Icon name="shield" cls="s" /></span>
        <div>What we store<span className="s">An access token and refresh token for {s.name}, encrypted, under your user. Not your password. Disconnecting revokes the token and deletes it.</span></div>
      </div>
      <div className="actions">
        {l.status === 'expired' && <button type="button" className="btn btn-primary btn-lg" onClick={act}><Icon name="refresh" />Reconnect</button>}
        {l.status !== 'expired' && l.status !== 'active' && <button type="button" className="btn btn-primary btn-lg" onClick={act}>Publish</button>}
        <button type="button" className="btn btn-outline btn-lg" style={{ color: 'var(--error)' }} onClick={() => overlay.open(<DisconnectSheet uuid={uuid} />, { sheet: true })}>Disconnect &amp; revoke</button>
        <button type="button" className="btn btn-secondary btn-lg" onClick={overlay.close}>Done</button>
      </div>
    </>
  );
}

function DisconnectSheet({ uuid }) {
  const { backend, me } = useClient();
  const overlay = useOverlay();
  const toast = useToast();
  const s = backend.catalog[uuid];
  const confirm = () => {
    overlay.close();
    backend.disconnect(me.id, uuid);
    toast(s.name + ' disconnected. Its token was revoked and deleted.', 'ok', 4500);
  };
  return (
    <>
      <h2>Disconnect {s.name}?</h2>
      <p className="muted" style={{ fontSize: 15 }}>We'll revoke the token with {s.name} and delete it. {s.name} stays published for other users; you can connect again any time.</p>
      <div className="actions">
        <button type="button" className="btn btn-danger btn-lg" onClick={confirm}>Disconnect &amp; revoke</button>
        <button type="button" className="btn btn-secondary btn-lg" onClick={() => overlay.open(<ManageSheet uuid={uuid} />, { sheet: true })}>Keep it</button>
      </div>
    </>
  );
}

export function PrivacySheet() {
  const overlay = useOverlay();
  return (
    <>
      <h2>Privacy and connected accounts</h2>
      <p className="muted" style={{ fontSize: 15, marginBottom: 12 }}>For each service you connect, we keep only what we need to act for you.</p>
      <div className="perm"><span className="ic"><Icon name="key" cls="s" /></span><div>Stored<span className="s">Access token, its expiry, refresh token and the permissions you granted, encrypted, under your user.</span></div></div>
      <div className="perm"><span className="ic"><Icon name="lock" cls="s" /></span><div>Never stored<span className="s">Your password. You always sign in on the service's own page.</span></div></div>
      <div className="perm"><span className="ic"><Icon name="user" cls="s" /></span><div>How calls know it's you<span className="s">Every call to a service's MCP URL carries your user token. The gateway reads it and uses your account, never anyone else's.</span></div></div>
      <div className="actions"><button type="button" className="btn btn-secondary btn-lg" onClick={overlay.close}>Done</button></div>
    </>
  );
}

export function NotificationsSheet() {
  const { backend, me } = useClient();
  const overlay = useOverlay();
  const items = backend.myServices(me.id).map((s) => s.name + ': ' + backend.statusOf(me.id, s.uuid).label.toLowerCase() + '.');
  if (!items.length) items.push('Nothing new. Onboard a service to get started.');
  return (
    <>
      <h2>Notifications</h2>
      <div className="stack-s" style={{ marginTop: 8 }}>
        {items.map((t) => <div className="tile" style={{ fontSize: 15 }} key={t}>{t}</div>)}
      </div>
      <div className="actions"><button type="button" className="btn btn-secondary btn-lg" onClick={overlay.close}>Done</button></div>
    </>
  );
}
