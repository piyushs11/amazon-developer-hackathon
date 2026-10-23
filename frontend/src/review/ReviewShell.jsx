import AccountMenu from '../components/AccountMenu.jsx';
import ConsoleShell, { NavItems } from '../components/ConsoleShell.jsx';
import { useOverlay } from '../components/Overlay.jsx';
import Icon from '../lib/Icon.jsx';
import { isOpen, useReview } from './reviewState.jsx';

export default function ReviewShell({ row2, nav, children }) {
  const overlay = useOverlay();
  const { reviewer, signOut } = useReview();

  const right = (
    <>
      <button className="btn-icon btn" aria-label="Review guidelines" title="Review guidelines" onClick={() => overlay.open(<Guidelines />)}>
        <Icon name="help" />
      </button>
      <AccountMenu
        initials={reviewer.initials}
        name={reviewer.name}
        detail={reviewer.email}
        items={[{ label: 'Sign out', onClick: signOut }]}
      />
    </>
  );

  return (
    <ConsoleShell brandTo="/review" subtitle="Review Console" right={right} row2={row2} nav={nav}>
      {children}
    </ConsoleShell>
  );
}

// Side nav for the Queue and Catalog pages.
export function TopNav({ current }) {
  const { subs } = useReview();
  return (
    <NavItems items={[
      { section: 'Review' },
      { label: 'Queue', to: '/review', current: current === 'queue', icon: 'list', count: subs.filter(isOpen).length },
      { label: 'Catalog', to: '/review/catalog', current: current === 'catalog', icon: 'grid', count: new Set(subs.filter((s) => s.status === 'approved').map((s) => s.domain)).size },
    ]} />
  );
}

function Guidelines() {
  const overlay = useOverlay();
  return (
    <>
      <h2>Review guidelines</h2>
      <p className="lede">Automated checks already verified the manifest, HTTPS, the hosted copy, the domain and the voice fields. You check what a customer will experience.</p>
      <ol className="guide" style={{ paddingLeft: 20, margin: 0 }}>
        <li><b>Try every tool</b> on the Try it tab: it signs in with the owner's test account and calls their real API. If sign-in fails, reject with "Test account doesn't work".</li>
        <li><b>Spoken replies</b> should answer the question with no codes or JSON.</li>
        <li><b>Payment and write tools ask first.</b> The confirmation must say what happens and what will be charged, and nothing runs without a yes.</li>
        <li><b>Privacy policy and terms</b> must open and cover account data.</li>
        <li><b>Approve</b> lists the service in the catalog. Its tools go live on the gateway when the first user publishes it, so approval costs nothing until someone uses it.</li>
      </ol>
      <div className="actions"><button className="btn btn-primary" onClick={overlay.close}>Got it</button></div>
    </>
  );
}
