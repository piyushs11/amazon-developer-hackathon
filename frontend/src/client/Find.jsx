import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import Icon from '../lib/Icon.jsx';
import { useClient } from './clientState.jsx';
import TopBar from './TopBar.jsx';

// Search results that need a screen of their own: several matches, or nothing on Alexa+.
export default function Find() {
  const { backend } = useClient();
  const [params] = useSearchParams();
  const q = params.get('q') || '';
  const res = backend.resolve(q);

  if (!res) return <Navigate to="/client/services" replace />;
  if (res.result.status === 'resolved') return <Navigate to={`/client/services/${res.result.uuid}`} replace />;
  if (res.result.status === 'ambiguous') return <Pick q={q} uuids={res.result.uuids} />;
  return <NotAvailable domain={res.result.domain} name={res.result.name} />;
}

function Pick({ q, uuids }) {
  const { backend } = useClient();
  const navigate = useNavigate();
  return (
    <div className="app">
      <TopBar title="Which one?" onBack={() => navigate('/client/services')} right={<span style={{ width: 38 }}></span>} />
      <div className="app-body">
        <p className="muted" style={{ fontSize: 15, padding: '4px 0 14px' }}>{uuids.length} services match "{q}". Pick the one you use.</p>
        <div className="stack-s">
          {uuids.map((u) => {
            const s = backend.catalog[u];
            return (
              <button type="button" className="pick-row" key={u} onClick={() => navigate(`/client/services/${u}`, { state: { fromPick: true } })}>
                <span className="logo" style={{ background: s.color }}>{s.initials}</span>
                <span className="grow"><b>{s.name}</b><span className="sub" style={{ display: 'block' }}>{s.domain} · {s.category} · {s.city}</span></span>
                <Icon name="chevron-right" cls="muted" />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function NotAvailable({ domain, name }) {
  const { setQuery, goSearch } = useClient();
  const navigate = useNavigate();
  return (
    <div className="app">
      <TopBar title="" onBack={() => navigate('/client/services')} right={null} />
      <div className="app-body">
        <div className="not-avail">
          <div className="ring"><Icon name="globe" /></div>
          <h1 style={{ font: '700 22px/28px var(--font-display)', marginTop: 6 }}>This service is not currently available on Alexa.</h1>
          <p className="muted" style={{ fontSize: 15 }}>
            {name
              ? `Nothing on Alexa+ matches "${name}". Try searching for its website instead.`
              : `${domain} hasn't been submitted to Alexa+ or hasn't been approved yet.`}
          </p>
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="btn btn-outline" onClick={() => { setQuery(''); goSearch(); }}>Search again</button>
          </div>
        </div>
      </div>
    </div>
  );
}
