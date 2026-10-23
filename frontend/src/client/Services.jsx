import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useOverlay } from '../components/Overlay.jsx';
import Switch from '../components/Switch.jsx';
import { useToast } from '../components/Toast.jsx';
import { mcpUrl } from '../data/manifest.js';
import Icon from '../lib/Icon.jsx';
import { useClient } from './clientState.jsx';
import { lastCalledText } from './bits.jsx';
import TopBar from './TopBar.jsx';
import { ManageSheet } from './sheets.jsx';

const MOCK_TRY = [['https://www.demobistro.test/menu', 'demobistro.test'], ['Lakeside', 'Lakeside'], ['pizzapalace.com', 'pizzapalace.com']];

// Search examples from the catalog: a website, a name several services share ("Which one?"),
// and a name with a city.
function tryChips(list) {
  if (!list?.length) return [];
  const chips = [['https://www.' + list[0].domain, list[0].domain]];
  const firstWords = list.map((s) => s.service_name.split(/\s+/)[0]);
  const shared = firstWords.find((w, i) => firstWords.indexOf(w) !== i);
  if (shared) chips.push([shared, shared]);
  const withCity = list.find((s) => s.profile?.city && s.service_name.split(/\s+/)[0] === shared) || list.find((s) => s.profile?.city);
  if (withCity) {
    const q = withCity.service_name.split(/\s+/)[0] + ' in ' + withCity.profile.city;
    chips.push([q, q]);
  }
  return chips;
}

// S1 dashboard plus the S2a search box.
export default function Services() {
  const { backend, me, query, setQuery } = useClient();
  const navigate = useNavigate();
  const toast = useToast();
  const location = useLocation();
  const [input, setInput] = useState(query);
  const inputRef = useRef(null);
  const list = backend.myServices(me.id);
  const chips = backend.catalogList ? tryChips(backend.catalogList()) : MOCK_TRY;

  useEffect(() => {
    if (!location.state?.focusSearch) return undefined;
    const t = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [location.state]);

  const resolve = async (raw) => {
    let res;
    try {
      res = await backend.resolve(raw);
    } catch (e) {
      toast(e.message, 'err');
      return;
    }
    if (!res) return;
    setQuery(res.query);
    if (res.result.status === 'resolved') navigate(`/client/services/${res.result.uuid}`);
    else navigate('/client/services/find?q=' + encodeURIComponent(raw.trim()));
  };

  return (
    <div className="app">
      <TopBar title="Services" />
      <div className="app-body">
        <form className="input-search" role="search" onSubmit={(e) => { e.preventDefault(); resolve(input); }}>
          <Icon name="search" />
          <input ref={inputRef} className="input" id="q" placeholder={'Website, like ' + (chips[0]?.[1] || 'example.com') + ', or a name'} value={input} onChange={(e) => setInput(e.target.value)}
            autoComplete="off" autoCapitalize="none" spellCheck="false" aria-label="Find a service by website or name" />
        </form>
        <div className="row wrap" style={{ padding: '10px 0 2px', fontSize: 13, color: 'var(--fg-2)' }} hidden={!chips.length}>
          Try {chips.map(([q, label]) => (
            <button type="button" className="chip" key={q} style={{ height: 30 }} onClick={() => { setInput(q); resolve(q); }}>{label}</button>
          ))}
        </div>

        <div className="section-h">
          Your services
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => inputRef.current.focus()}><Icon name="plus" />Onboard a service</button>
        </div>
        {list.length ? (
          <div className="stack-s">{list.map((s) => <ServiceCard key={s.uuid} s={s} />)}</div>
        ) : (
          <p className="empty">No services yet. Onboard one by searching for its website. You sign in on the service's own page; we never see your password.</p>
        )}

        <div className="section-h">How it works</div>
        <div className="stack-s">
          <div className="perm"><span className="ic"><Icon name="search" cls="s" /></span><div>Find the service<span className="s">Search by website. Approved services can be connected; others show as not available.</span></div></div>
          <div className="perm"><span className="ic"><Icon name="lock" cls="s" /></span><div>Connect your account<span className="s">You sign in on their site. We store a token for you, never your password.</span></div></div>
          <div className="perm"><span className="ic"><Icon name="bolt" cls="s" /></span><div>Publish<span className="s">Its tools go live at one MCP URL for the service. Everyone shares the URL; your token decides whose account is used.</span></div></div>
        </div>
      </div>
    </div>
  );
}

function ServiceCard({ s }) {
  const { backend, me, rowAction } = useClient();
  const overlay = useOverlay();
  const toast = useToast();
  const st = backend.statusOf(me.id, s.uuid);
  const live = backend.isPublished(s.uuid);

  const action = s.status === 'expired' ? <><Icon name="refresh" />Reconnect</>
    : s.status === 'connected' ? 'Publish'
      : s.status === 'failed' ? <><Icon name="refresh" />Retry publish</>
        : s.update ? <><Icon name="refresh" />Update</> : null;

  const toggle = async (on) => {
    try {
      await backend.setEnabled(me.id, s.uuid, on);
      toast(s.name + (on ? ' is on' : ' is off'), '', 1800);
    } catch (e) {
      toast(e.message, 'err');
    }
  };

  return (
    <div className="svc-card">
      <div className="logo" style={{ background: s.color }}>{s.initials}</div>
      <div>
        <div className="name">{s.name}</div>
        <div className="meta"><span className={'status ' + st.cls}>{st.label}</span><span>{lastCalledText(s.lastCalled)}</span></div>
      </div>
      <div className="side">
        {s.status === 'active' && <Switch on={s.on} onChange={toggle} label={'Use ' + s.name + ' with Alexa'} />}
        <button type="button" className="btn-icon btn sm plain" aria-label={'Manage ' + s.name} onClick={() => overlay.open(<ManageSheet uuid={s.uuid} />, { sheet: true })}>
          <Icon name="chevron-right" />
        </button>
      </div>
      <div><span className="mcp">{live ? mcpUrl(s.uuid) : 'MCP URL appears after the first publish'}</span></div>
      {action && <div className="act"><button type="button" className="btn btn-primary btn-sm" onClick={() => rowAction(s.uuid)}>{action}</button></div>}
    </div>
  );
}
