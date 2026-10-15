import { useNavigate } from 'react-router-dom';
import { Row2 } from '../components/ConsoleShell.jsx';
import { mcpUrl } from '../data/manifest.js';
import { fmtDate, fmtDateTime } from '../lib/utils.js';
import ReviewShell, { TopNav } from './ReviewShell.jsx';
import { useReview } from './reviewState.jsx';

export default function Catalog() {
  const { subs } = useReview();
  const navigate = useNavigate();
  const rows = subs.filter((s) => s.status === 'approved').sort((a, b) => b.reviewed - a.reviewed);

  return (
    <ReviewShell row2={<Row2 title="Catalog" />} nav={<TopNav current="catalog" />}>
      <div className="page-head"><div>
        <h1>Catalog</h1>
        <p className="lede">
          Approved connectors Alexa+ users can add by searching for the website. Each service gets one MCP URL on the gateway, <code>/mcp/{'{service_uuid}'}</code>.
          {' '}Its tool bundle is generated the first time any user publishes it; later users reuse the active bundle, and their user token decides whose account each call uses.
        </p>
      </div></div>

      <div className="card pad-0"><div className="table-wrap">
        <table className="tbl cards">
          <thead><tr><th>Service</th><th>Domain</th><th>Approved</th><th>Active bundle</th><th>Connected users</th><th>MCP URL</th></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className="clickable" onClick={() => navigate(`/review/${s.id}/summary`)}>
                <td className="primary" data-l="Service">{s.service}</td>
                <td data-l="Domain">{s.domain}</td>
                <td data-l="Approved">{fmtDate(s.reviewed)} · {s.reviewer}</td>
                <td data-l="Active bundle">
                  {s.server ? (
                    <><span className="status live">Live · {s.server.version}</span><div className="small muted">Published {fmtDateTime(s.server.published)}</div></>
                  ) : (
                    <><span className="status">Not published yet</span><div className="small muted">Goes live on the first user's publish</div></>
                  )}
                </td>
                <td data-l="Connected users" className="tnum">{s.server ? s.server.users : 0}</td>
                <td data-l="MCP URL"><code style={{ overflowWrap: 'anywhere' }}>{mcpUrl(s.uuid)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div></div>

      <div className="section"><div className="card">
        <h2 style={{ marginBottom: 8 }}>Server details</h2>
        <p className="muted">Every generated server speaks MCP 2025-11-25 over Streamable HTTP and passes an initialize + tools/list health check before it is marked live. Calls carry a signed Alexa-user token; the server reads that user's access token from the vault, refreshes it if expired, and calls the owner's API.</p>
      </div></div>
    </ReviewShell>
  );
}
