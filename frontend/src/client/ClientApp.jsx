import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { OverlayProvider } from '../components/Overlay.jsx';
import Icon from '../lib/Icon.jsx';
import useBodyClass from '../lib/useBodyClass.js';
import { ClientProvider, useClient } from './clientState.jsx';
import Login from './Login.jsx';
import Home from './Home.jsx';
import Services from './Services.jsx';
import Find from './Find.jsx';
import ServiceDetail from './ServiceDetail.jsx';
import More from './More.jsx';
import OAuthWindow from './OAuthWindow.jsx';
import PublishScreen from './PublishScreen.jsx';
import Simulator from './Simulator.jsx';
import './client.css';

export default function ClientApp() {
  useEffect(() => { document.title = 'MCP Bridge Alexa+ App'; }, []);
  return (
    <ClientProvider>
      <OverlayProvider>
        <ClientShell />
      </OverlayProvider>
    </ClientProvider>
  );
}

function ClientShell() {
  const { me, layer } = useClient();
  const { pathname } = useLocation();
  useBodyClass('client-page app-bg' + (layer ? ' has-full' : ''));
  useEffect(() => { window.scrollTo(0, 0); }, [pathname, me]);

  if (!me) return <Login />;

  return (
    <>
      <Routes>
        <Route index element={<Home />} />
        <Route path="services" element={<Services />} />
        <Route path="services/find" element={<Find />} />
        <Route path="services/:uuid" element={<ServiceDetail />} />
        <Route path="more" element={<More />} />
        <Route path="*" element={<Navigate to="/client" replace />} />
      </Routes>
      <BottomBar />
      {layer?.type === 'oauth' && <OAuthWindow key={layer.id} uuid={layer.uuid} />}
      {layer?.type === 'publish' && <PublishScreen key={layer.id} uuid={layer.uuid} />}
      {layer?.type === 'sim' && <Simulator key={layer.id} opts={layer.opts} />}
    </>
  );
}

const TABS = [['home', 'home', 'Home', '/client'], ['services', 'grid', 'Services', '/client/services'], ['more', 'menu', 'More', '/client/more']];

function BottomBar() {
  const { openSim } = useClient();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const current = pathname.startsWith('/client/services') ? 'services' : pathname.startsWith('/client/more') ? 'more' : 'home';

  return (
    <div className="app-bottom">
      <div className="inner">
        <nav className="tabbar" aria-label="Main">
          {TABS.map(([key, icon, label, to]) => (
            <button type="button" key={key} aria-current={current === key ? 'page' : undefined} aria-label={label} onClick={() => navigate(to)}>
              <Icon name={icon} />
            </button>
          ))}
        </nav>
        <button type="button" className="ask grow" aria-label="Ask Alexa" onClick={(e) => openSim(e.target.closest('[data-mic]') ? { listen: true } : {})}>
          <span className="orb"></span>
          <span className="grow" style={{ textAlign: 'left', color: 'var(--fg-3)', fontSize: 16 }}>Ask Alexa</span>
          <span className="btn-icon btn" data-mic role="button" aria-label="Speak to Alexa"><Icon name="mic" /></span>
        </button>
      </div>
    </div>
  );
}
