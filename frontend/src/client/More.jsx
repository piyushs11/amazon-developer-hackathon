import { useNavigate } from 'react-router-dom';
import { useOverlay } from '../components/Overlay.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { useClient } from './clientState.jsx';
import TopBar from './TopBar.jsx';
import { PrivacySheet } from './sheets.jsx';

export default function More() {
  const { backend, me, signIn, signOut, openSim } = useClient();
  const navigate = useNavigate();
  const overlay = useOverlay();
  const toast = useToast();
  const others = backend.users().filter((u) => u.id !== me.id);

  const switchTo = (u) => {
    signIn(u.id);
    navigate('/client');
    toast('Signed in as ' + u.name, 'ok', 2000);
  };

  return (
    <div className="app">
      <TopBar title="More" />
      <div className="app-body">
        <div className="section-h">Signed in</div>
        <div className="profile-row">
          <span className="av" style={{ background: me.color }}>{me.name[0]}</span>
          <span><b>{me.name}</b><span className="small muted" style={{ display: 'block' }}>user_id {me.id} · user token active</span></span>
        </div>

        <div className="section-h">Switch user</div>
        {others.map((u) => (
          <button type="button" className="profile-row" key={u.id} onClick={() => switchTo(u)}>
            <span className="av" style={{ background: u.color }}>{u.name[0]}</span>
            <span><b>{u.name}</b><span className="small muted" style={{ display: 'block' }}>{Object.keys(u.services).length} services</span></span>
            <span className="cur"><Icon name="chevron-right" /></span>
          </button>
        ))}

        <div className="section-h">Alexa+</div>
        <button type="button" className="list-row" onClick={() => navigate('/client/services')}><Icon name="grid" />Services<span className="chev"><Icon name="chevron-right" /></span></button>
        <button type="button" className="list-row" onClick={() => openSim({ mode: 'tools' })}><Icon name="terminal" />Simulator<span className="chev"><Icon name="chevron-right" /></span></button>
        <button type="button" className="list-row" onClick={() => overlay.open(<PrivacySheet />, { sheet: true })}><Icon name="shield" />Privacy and connected accounts<span className="chev"><Icon name="chevron-right" /></span></button>
        <button type="button" className="list-row" onClick={() => { signOut(); navigate('/client'); }}><Icon name="arrow-left" />Sign out<span className="chev"><Icon name="chevron-right" /></span></button>
      </div>
    </div>
  );
}
