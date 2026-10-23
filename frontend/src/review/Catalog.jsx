import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Row2 } from '../components/ConsoleShell.jsx';
import NotBuilt from '../components/NotBuilt.jsx';
import { mcpUrl } from '../data/manifest.js';
import { toDate } from '../lib/portal.js';
import { fmtDate, fmtDateTime } from '../lib/utils.js';
import ReviewShell, { TopNav } from './ReviewShell.jsx';
import { useReview } from './reviewState.jsx';

// GET /api/review/catalog: approved services, their active bundle and connected users.
export default function Catalog() {
  const { catalog, subs } = useReview();
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { catalog().then(setRows).catch((e) => setError(e.message)); }, [catalog]);

  // Open the approved submission behind a catalog row.
  const openRow = (r) => {
    const sub = subs.find((s) => s.domain === r.domain && s.status === 'approved');
    if (sub) navigate(`/review/${sub.id}/summary`);
  };

  return (
    <ReviewShell row2={<Row2 title="Catalog" />} nav={<TopNav current="catalog" />}>
      <div className="page-head"><div>
        <h1>Catalog</h1>
        <p className="lede">
          Approved connectors Alexa+ users can add by searching for the website. Each service gets one MCP URL on the gateway, <code>/mcp/{'{service_uuid}'}</code>.
          {' '}Its tool bundle is generated the first time any user publishes it; later users reuse the active bundle, and their user token decides whose account each call uses.
        </p>
      </div></div>

      {error && <div className="banner err"><div>{error}</div></div>}
      <div className="card pad-0"><div className="table-wrap">
        <table className="tbl cards">
          <thead><tr><th>Service</th><th>Domain</th><th>Approved</th><th>Active bundle</th><th>Connected users</th><th>MCP URL</th></tr></thead>
          <tbody>
            {(rows || []).map((r) => (
              <tr key={r.service_uuid} className="clickable" onClick={() => openRow(r)}>
                <td className="primary" data-l="Service">{r.service_name}<div className="small muted">{r.business}</div></td>
                <td data-l="Domain">{r.domain}</td>
                <td data-l="Approved">{r.approved_version ? `v${r.approved_version} · ${fmtDate(toDate(r.approved_at))}` : <span className="muted">Seeded</span>}</td>
                <td data-l="Active bundle">
                  {r.published ? (
                    <><span className="status live">Live · version {r.bundle_version}</span><div className="small muted">Published {fmtDateTime(toDate(r.published_at))} · {r.tools_count} tools</div></>
                  ) : (
                    <><span className="status">Not published yet</span><div className="small muted">Goes live on the first user's publish</div></>
                  )}
                </td>
                <td data-l="Connected users" className="tnum">{r.connected_users}</td>
                <td data-l="MCP URL"><code style={{ overflowWrap: 'anywhere' }}>{mcpUrl(r.service_uuid)}</code></td>
              </tr>
            ))}
            {!rows && !error && <tr><td colSpan={6} className="muted" style={{ padding: '28px 16px', textAlign: 'center' }}>Loading...</td></tr>}
          </tbody>
        </table>
      </div></div>

      <div className="section"><div className="card">
        <h2 style={{ marginBottom: 8 }}>Server details</h2>
        <p className="muted">
          Every bundle speaks MCP (2025-11-25, 2025-06-18) over Streamable HTTP on the shared gateway and must load cleanly before it is marked active.
          Calls carry the user's token; the gateway reads that user's access token for the service, refreshes it when it expires, and calls the owner's API.
          {' '}Alexa+ registration <NotBuilt id="alexa_registration" label="mocked" />
        </p>
      </div></div>
    </ReviewShell>
  );
}
