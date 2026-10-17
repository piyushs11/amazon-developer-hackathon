import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useOverlay } from '../components/Overlay.jsx';
import Icon from '../lib/Icon.jsx';
import { useClient } from './clientState.jsx';
import { DB } from './mockBackend.js';
import { ToolList } from './bits.jsx';
import TopBar from './TopBar.jsx';
import { ConnectSheet, ManageSheet } from './sheets.jsx';

export default function ServiceDetail() {
  const { uuid } = useParams();
  const { backend, me, openSim } = useClient();
  const overlay = useOverlay();
  const navigate = useNavigate();
  const location = useLocation();
  const s = backend.catalog[uuid];
  if (!s) return <Navigate to="/client/services" replace />;

  const link = backend.link(me.id, uuid);
  const back = () => (location.state?.fromPick ? navigate(-1) : navigate('/client/services'));

  return (
    <div className="app">
      <TopBar title="" onBack={back} right={null} />
      <div className="app-body">
        <div className="svc-hero">
          <div className="logo" style={{ background: s.color }}>{s.initials}</div>
          <h1>{s.name}</h1>
          <div className="dom">{s.domain}</div>
          <div className="cat">{s.category} · {s.city} · Approved for Alexa+</div>
        </div>
        {link ? (
          <div className="row" style={{ gap: 10 }}>
            <button type="button" className="btn btn-secondary btn-lg grow" onClick={() => overlay.open(<ManageSheet uuid={uuid} />, { sheet: true })}>
              <Icon name="check" />Connected · Manage
            </button>
            {backend.access(me.id, uuid) === 'ok' && (
              <button type="button" className="btn btn-primary btn-lg" style={{ padding: '0 18px' }} onClick={() => openSim(uuid === DB ? {} : { mode: 'tools', uuid })}>Ask</button>
            )}
          </div>
        ) : (
          <>
            <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => overlay.open(<ConnectSheet uuid={uuid} />, { sheet: true })}>Connect</button>
            <div className="store-note">Requires a {s.name} account</div>
          </>
        )}
        <p style={{ padding: '18px 0 4px' }}>{s.description}</p>
        <div className="section-h">Things to try</div>
        <ul className="say-list">{s.phrases.map((p) => <li key={p}>{p}</li>)}</ul>
        <div className="section-h">Tools</div>
        <ToolList tools={s.tools} />
        <div className="links-row">
          <a href={s.privacy} target="_blank" rel="noopener">Privacy policy</a>
          <a href={s.terms} target="_blank" rel="noopener">Terms</a>
        </div>
        <div style={{ height: 16 }}></div>
      </div>
    </div>
  );
}
