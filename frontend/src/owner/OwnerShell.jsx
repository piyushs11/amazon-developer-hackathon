import AccountMenu from '../components/AccountMenu.jsx';
import ConsoleShell from '../components/ConsoleShell.jsx';
import Icon from '../lib/Icon.jsx';
import { useOwner } from './ownerState.jsx';

export const GUIDE_PDF = '/docs/owner-submission-guide.pdf';
// Example manifests a business can start from (Pine & Petal: 1.0, and 1.1 which adds order tracking).
export const SAMPLES = [
  { href: '/examples/pinepetal-1.0.json', label: 'Sample manifest (Pine & Petal 1.0)' },
  { href: '/examples/pinepetal-1.1.json', label: 'Sample update (Pine & Petal 1.1)' },
];

export default function OwnerShell({ row2, nav, children }) {
  const { owner, signOut } = useOwner();

  const right = (
    <>
      <a className="btn-icon btn" href={GUIDE_PDF} target="_blank" rel="noopener" aria-label="Owner submission guide" title="Owner submission guide (PDF)">
        <Icon name="help" />
      </a>
      <AccountMenu
        initials={owner.initials}
        name={owner.name}
        detail={owner.email}
        items={[{ label: 'Sign out', onClick: signOut }]}
      />
    </>
  );

  return (
    <ConsoleShell brandTo="/owner" subtitle="Owner Portal" right={right} row2={row2} nav={nav}>
      {children}
    </ConsoleShell>
  );
}
