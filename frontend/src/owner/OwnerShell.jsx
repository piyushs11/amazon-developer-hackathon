import AccountMenu from '../components/AccountMenu.jsx';
import ConsoleShell from '../components/ConsoleShell.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { useOwner } from './ownerState.jsx';

export const GUIDE_PDF = '/docs/owner-submission-guide.pdf';
export const SAMPLE_MANIFEST = '/examples/demobistro/alexa-connector.upload.json';

export default function OwnerShell({ row2, nav, children }) {
  const { owner } = useOwner();
  const toast = useToast();

  const right = (
    <>
      <a className="btn-icon btn" href={GUIDE_PDF} target="_blank" rel="noopener" aria-label="Owner submission guide" title="Owner submission guide (PDF)">
        <Icon name="help" />
      </a>
      <AccountMenu
        initials="DB"
        name={owner.name}
        detail={owner.email}
        items={[
          { label: 'Organization settings', onClick: () => toast('Organization settings are managed by your account owner.') },
          { label: 'Sign out', onClick: () => toast('Signed out of the demo account. Reload to sign in again.') },
        ]}
      />
    </>
  );

  return (
    <ConsoleShell brandTo="/owner" subtitle="Owner Portal" right={right} row2={row2} nav={nav}>
      {children}
    </ConsoleShell>
  );
}
