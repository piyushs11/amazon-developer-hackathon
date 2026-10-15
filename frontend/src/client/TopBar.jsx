import { useNavigate } from 'react-router-dom';
import { useOverlay } from '../components/Overlay.jsx';
import Icon from '../lib/Icon.jsx';
import { useClient } from './clientState.jsx';
import { NotificationsSheet } from './sheets.jsx';

// Top bar of the app screens. `right` replaces the bell and avatar (pass null for nothing).
export default function TopBar({ title, onBack, right }) {
  const { backend, me } = useClient();
  const navigate = useNavigate();
  const overlay = useOverlay();
  const needsAttention = backend.myServices(me.id).some((s) => s.status === 'expired');

  return (
    <div className="app-top">
      {onBack ? (
        <button type="button" className="btn-icon btn" aria-label="Back" onClick={onBack}><Icon name="chevron-left" /></button>
      ) : (
        <button type="button" className="btn-icon btn" aria-label="Menu" onClick={() => navigate('/client/more')}><Icon name="menu" /></button>
      )}
      <div className="title">{title || ''}</div>
      {right !== undefined ? right : (
        <>
          <button type="button" className="btn-icon btn" style={{ position: 'relative' }} aria-label="Notifications" onClick={() => overlay.open(<NotificationsSheet />, { sheet: true })}>
            <Icon name="bell" />{needsAttention && <span className="badge-dot"></span>}
          </button>
          <button type="button" className="avatar" style={{ background: me.color, width: 38, height: 38, fontSize: 15 }} aria-label={'Signed in as ' + me.name} onClick={() => navigate('/client/more')}>
            {me.name[0]}
          </button>
        </>
      )}
    </div>
  );
}
