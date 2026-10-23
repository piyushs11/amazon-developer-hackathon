import { useNavigate } from 'react-router-dom';
import { NavItems, Row2 } from '../components/ConsoleShell.jsx';
import Icon from '../lib/Icon.jsx';
import { fmtDate } from '../lib/utils.js';
import OwnerShell, { GUIDE_PDF, SAMPLES } from './OwnerShell.jsx';
import { StatusLabel, useOwner } from './ownerState.jsx';

export default function ConnectorList() {
  const { connectors, error, resetWizard } = useOwner();
  const navigate = useNavigate();

  const nav = (
    <NavItems items={[
      { section: 'Portal' },
      { label: 'Your connectors', to: '/owner', current: true, icon: 'grid' },
      { section: 'Resources' },
      { label: 'Owner submission guide (PDF)', href: GUIDE_PDF, ext: true, icon: 'pdf' },
      ...SAMPLES.map((s) => ({ label: s.label, href: s.href, ext: true, icon: 'file' })),
    ]} />
  );
  const newSubmission = () => { resetWizard(null); navigate('/owner/submit/1'); };

  return (
    <OwnerShell row2={<Row2 title="Your connectors" />} nav={nav}>
      <div className="page-head">
        <div>
          <h1>Your connectors</h1>
          <p className="lede">One connector per website. Upload a manifest, pass the automated checks, and Amazon reviews it. Approved connectors appear in the Alexa+ catalog.</p>
        </div>
        <div className="actions">
          <button className="btn btn-primary" onClick={newSubmission}><Icon name="plus" />New submission</button>
        </div>
      </div>

      {error && <div className="banner err"><Icon name="alert" /><div>{error}</div></div>}
      <div className="card pad-0"><div className="table-wrap">
        <table className="tbl cards">
          <thead><tr><th>Connector</th><th>Domain</th><th>Category</th><th>Latest version</th><th>Status</th><th>Updated</th></tr></thead>
          <tbody>
            {(connectors || []).map((c) => {
              const latest = c.submissions[0];
              return (
                <tr key={c.service_uuid} className="clickable" onClick={() => navigate(`/owner/${c.service_uuid}/overview`)}>
                  <td className="primary" data-l="Connector">{c.service_name}</td>
                  <td data-l="Domain">{c.domain}</td>
                  <td data-l="Category">{c.category || <span className="muted">-</span>}</td>
                  <td data-l="Latest version" className="tnum">{latest?.version || c.live_version || '-'}</td>
                  <td data-l="Status"><StatusLabel status={c.status} /></td>
                  <td data-l="Updated">{latest ? fmtDate(latest.reviewed || latest.submitted) : '-'}</td>
                </tr>
              );
            })}
            {connectors && !connectors.length && (
              <tr><td colSpan={6} className="muted" style={{ padding: '28px 16px', textAlign: 'center' }}>No connectors yet. Start with a new submission.</td></tr>
            )}
            {!connectors && !error && (
              <tr><td colSpan={6} className="muted" style={{ padding: '28px 16px', textAlign: 'center' }}>Loading...</td></tr>
            )}
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
          {SAMPLES.map((s) => (
            <a className="card" key={s.href} href={s.href} target="_blank" rel="noopener">
              <Icon name="file" cls="l" /><h3>{s.label}</h3>
              <p>A complete manifest for a florist: OpenAPI endpoints with x-alexa phrases and templates, account linking and a test account.</p>
              <span className="row">Open <Icon name="external" cls="s" /></span>
            </a>
          ))}
        </div>
      </div>
    </OwnerShell>
  );
}
