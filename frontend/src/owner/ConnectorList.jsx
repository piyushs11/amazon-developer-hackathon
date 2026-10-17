import { useNavigate } from 'react-router-dom';
import { NavItems, Row2 } from '../components/ConsoleShell.jsx';
import CopyButton from '../components/CopyButton.jsx';
import Icon from '../lib/Icon.jsx';
import { fmtDate } from '../lib/utils.js';
import OwnerShell, { GUIDE_PDF, SAMPLE_MANIFEST } from './OwnerShell.jsx';
import { StatusLabel, useOwner } from './ownerState.jsx';

export default function ConnectorList() {
  const { owner, latest: l } = useOwner();
  const navigate = useNavigate();
  const hostedUrl = `https://${owner.domain}/.well-known/alexa-connector.json`;

  const nav = (
    <NavItems items={[
      { section: 'Portal' },
      { label: 'Your connectors', to: '/owner', current: true, icon: 'grid' },
      { section: 'Resources' },
      { label: 'Owner submission guide (PDF)', href: GUIDE_PDF, ext: true, icon: 'pdf' },
      { label: 'Sample manifest', href: SAMPLE_MANIFEST, ext: true, icon: 'file' },
    ]} />
  );

  return (
    <OwnerShell row2={<Row2 title="Your connectors" />} nav={nav}>
      <div className="page-head">
        <div>
          <h1>Your connectors</h1>
          <p className="lede">One connector per website. Upload a manifest, pass the automated checks, and Amazon reviews it. Approved connectors appear in the Alexa+ catalog.</p>
        </div>
        <div className="actions">
          <button className="btn btn-primary" onClick={() => navigate('/owner/submit/1')}><Icon name="plus" />New submission</button>
        </div>
      </div>

      <div className="card pad-0"><div className="table-wrap">
        <table className="tbl cards">
          <thead><tr><th>Connector</th><th>Domain</th><th>Category</th><th>Latest version</th><th>Status</th><th>Updated</th></tr></thead>
          <tbody>
            <tr className="clickable" onClick={() => navigate('/owner/demobistro/overview')}>
              <td className="primary" data-l="Connector">{owner.name}</td>
              <td data-l="Domain">{owner.domain}</td>
              <td data-l="Category">Food &amp; drink</td>
              <td data-l="Latest version" className="tnum">{l.version}</td>
              <td data-l="Status"><StatusLabel status={l.status} /></td>
              <td data-l="Updated">{fmtDate(l.reviewed || l.submitted)}</td>
            </tr>
          </tbody>
        </table>
      </div></div>

      <div className="section">
        <h2>Resources</h2>
        <div className="res-grid">
          <a className="card" href={GUIDE_PDF} target="_blank" rel="noopener">
            <Icon name="pdf" cls="l" /><h3>Owner submission guide</h3>
            <p>How to write the manifest, host the public copy, and what reviewers check. PDF.</p>
            <span className="row">Open <Icon name="external" cls="s" /></span>
          </a>
          <a className="card" href={SAMPLE_MANIFEST} target="_blank" rel="noopener">
            <Icon name="file" cls="l" /><h3>Sample manifest</h3>
            <p>alexa-connector.upload.json for a restaurant with 3 endpoints. Copy it as a starting point.</p>
            <span className="row">Open <Icon name="external" cls="s" /></span>
          </a>
          <div className="card">
            <Icon name="globe" cls="l" /><h3>Host the public copy</h3>
            <p>Publish your manifest without the private block at this address. It proves you own the domain and powers search by website.</p>
            <div className="row">
              <code className="grow" style={{ overflowWrap: 'anywhere' }}>{hostedUrl}</code>
              <CopyButton value={hostedUrl} />
            </div>
          </div>
        </div>
      </div>
    </OwnerShell>
  );
}
