import { useNavigate } from 'react-router-dom';
import Icon from '../lib/Icon.jsx';
import { useClient } from './clientState.jsx';
import { DB } from './mockBackend.js';
import { greeting } from './bits.jsx';
import TopBar from './TopBar.jsx';

export default function Home() {
  const { backend, me, openSim, rowAction, goSearch } = useClient();
  const navigate = useNavigate();
  const list = backend.myServices(me.id);

  const suggestions = [];
  if (backend.live) {
    // One suggestion per live service, from the example phrases its business wrote.
    list.filter((s) => s.status === 'active' && s.on && s.askPhrase).slice(0, 3).forEach((s) => {
      const phrase = s.askPhrase;
      suggestions.push({ t: phrase[0].toUpperCase() + phrase.slice(1), s: s.name + ' · ' + (s.tagline || s.category), ic: s.glyph || 'bolt', c: s.color, go: () => openSim({ send: phrase }) });
    });
  } else if (backend.access(me.id, DB) === 'ok') {
    suggestions.push({ t: 'Check order A1042', s: 'Demo Bistro · "what is the status of order A1042"', ic: 'clock', c: '#126dff', go: () => openSim({ send: 'What is the status of order A1042' }) });
    suggestions.push({ t: 'Order from Demo Bistro', s: 'Try "order a paneer wrap from Demo Bistro"', ic: 'utensils', c: '#b23a1e', go: () => openSim({ send: 'What wraps does Demo Bistro have' }) });
  }
  const fix = list.find((s) => ['expired', 'connected', 'failed'].includes(s.status));
  if (fix) {
    const expired = fix.status === 'expired';
    suggestions.push({
      t: (expired ? 'Reconnect ' : 'Publish ') + fix.name,
      s: expired ? 'Your sign-in expired' : 'Connected, not on Alexa+ yet',
      ic: 'alert', c: '#cc0c39', go: () => rowAction(fix.uuid),
    });
  }
  const example = backend.catalogList?.()[0]?.domain || (backend.live ? 'example.com' : 'demobistro.test');
  suggestions.push({ t: list.length ? 'Onboard another service' : 'Onboard a service', s: 'Search by website, like ' + example, ic: 'search', c: '#1f6f8b', go: goSearch });

  return (
    <div className="app home">
      <div className="home-top-gradient"></div>
      <TopBar />
      <div className="app-body">
        <div className="home-deck">
          <button type="button" className="deck-row" onClick={() => navigate('/client/services')}>
            <Icon name="grid" />Services<span className="pillstat">{list.length ? list.length + ' connected' : 'None yet'}</span><Icon name="chevron-right" cls="s" />
          </button>
          <h1 className="greet">{greeting()} {me.name}, how can I help you?</h1>
          <div className="pills">
            {suggestions.map((x) => (
              <button type="button" className="pill-sug" key={x.t} onClick={x.go}>
                <span className="ic" style={{ background: x.c }}><Icon name={x.ic} /></span>
                <span><span className="t">{x.t}</span><span className="s">{x.s}</span></span>
              </button>
            ))}
            <button type="button" className="pill-sug" onClick={() => openSim({})}>
              <span className="ic" style={{ background: 'var(--blue-tint)', color: 'var(--blue)' }}><Icon name="history" /></span>
              <span className="t">Recent chats</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
