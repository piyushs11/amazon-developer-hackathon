import { useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { NavItems, Row2 } from '../components/ConsoleShell.jsx';
import { CheckRunner } from '../components/ChecksList.jsx';
import ToolCard from '../components/ToolCard.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { jsonHTML } from '../lib/json.js';
import { fmtDateTime } from '../lib/utils.js';
import { MANIFEST, SCOPE_LABELS, SERVICE_UUID, mcpUrl } from '../data/manifest.js';
import { TOOLS } from '../data/tools.js';
import OwnerShell, { GUIDE_PDF, SAMPLE_MANIFEST } from './OwnerShell.jsx';
import { StatusLabel, useOwner } from './ownerState.jsx';

const PUB = MANIFEST.publisher;
const TABS = [
  ['overview', 'Overview', 'grid'],
  ['checks', 'Automated checks', 'shield'],
  ['tools', 'Tools for Alexa+', 'bolt'],
  ['manifest', 'Manifest', 'file'],
  ['linking', 'Account linking', 'key'],
  ['submissions', 'Submissions', 'history'],
];

// The hosted /.well-known copy is the upload without the private block.
const hostedManifest = () => { const m = JSON.parse(JSON.stringify(MANIFEST)); delete m.private; return m; };

export default function ConnectorDetail() {
  const { tab } = useParams();
  const { owner, latest: l } = useOwner();
  if (!TABS.some((t) => t[0] === tab)) return <Navigate to="/owner/demobistro/overview" replace />;

  const nav = (
    <NavItems items={[
      { section: 'Connector' },
      ...TABS.map((t) => ({ label: t[1], to: '/owner/demobistro/' + t[0], current: t[0] === tab, icon: t[2] })),
      { section: 'Resources' },
      { label: 'Owner submission guide (PDF)', href: GUIDE_PDF, ext: true, icon: 'pdf' },
    ]} />
  );
  const row2 = (
    <Row2
      back={{ to: '/owner', label: 'Your connectors' }}
      title={owner.name}
      extra={<span className="title" style={{ fontWeight: 400, color: '#dbe7f0' }}><StatusLabel status={l.status} /></span>}
    />
  );

  return (
    <OwnerShell row2={row2} nav={nav}>
      {tab === 'overview' && <Overview />}
      {tab === 'checks' && <ChecksTab />}
      {tab === 'tools' && <ToolsTab />}
      {tab === 'manifest' && <ManifestTab />}
      {tab === 'linking' && <LinkingTab />}
      {tab === 'submissions' && <SubmissionsTab />}
    </OwnerShell>
  );
}

function NewSubmissionButton() {
  const navigate = useNavigate();
  return (
    <div className="actions">
      <button className="btn btn-primary" onClick={() => navigate('/owner/submit/1')}><Icon name="plus" />New submission</button>
    </div>
  );
}

/* ------------------------------------------------------------- overview */
function Step({ cls, title, desc, ic }) {
  return (
    <li className={cls}>
      <span className="dot">{ic ? <Icon name={ic} /> : null}</span>
      <div><div className="t">{title}</div><div className="d">{desc}</div></div>
    </li>
  );
}

function Timeline({ l }) {
  return (
    <ol className="timeline">
      <Step cls="done" title="Submitted" desc={'Version ' + l.version + ' · ' + fmtDateTime(l.submitted)} ic="check" />
      <Step cls="done" title="Automated checks passed" desc="8 of 8 · schema, OpenAPI, HTTPS, hosted copy, domain, voice fields, payment confirmation, endpoint limit" ic="check" />
      {l.status === 'in_review' && (<>
        <Step cls="now" title="In review" desc="An Amazon reviewer reads the check report and tool preview, then signs in with your test account and tries the tools in the Alexa+ simulator." />
        <Step cls="todo" title="Approved" desc="Demo Bistro is listed in the catalog. Its tools are generated once and go live at its MCP URL the first time a user publishes it." />
      </>)}
      {l.status === 'rejected' && (<>
        <Step cls="done" title="In review" desc={'Reviewed ' + fmtDateTime(l.reviewed)} ic="check" />
        <Step cls="fail" title="Rejected" desc="See the reason above. Fix it and submit a new version; the checks run again automatically." ic="x" />
      </>)}
      {l.status !== 'in_review' && l.status !== 'rejected' && (<>
        <Step cls="done" title="In review" desc={'Reviewed ' + fmtDateTime(l.reviewed)} ic="check" />
        <Step cls="done" title="Approved" desc="Listed in the Alexa+ catalog." ic="check" />
      </>)}
    </ol>
  );
}

function Overview() {
  const { latest: l } = useOwner();
  const al = MANIFEST.accountLinking;
  return (
    <>
      <div className="page-head">
        <div><h1>Overview</h1><p className="lede">{PUB.description}</p></div>
        {l.status !== 'in_review' && <NewSubmissionButton />}
      </div>
      <div className="stack">
        <div className="card status-card">
          <div>
            <div className="small muted" style={{ marginBottom: 6 }}>Connector status</div>
            <StatusLabel status={l.status} big />
          </div>
          <div className="last">
            <div><b>LAST SUBMITTED</b>{fmtDateTime(l.submitted)} · version {l.version}</div>
            {l.reviewed
              ? <div><b>REVIEWED</b>{fmtDateTime(l.reviewed)}</div>
              : <div><b>REVIEW</b>Usually done within 2 business days</div>}
          </div>
        </div>
        {l.status === 'rejected' && (
          <div className="banner err"><Icon name="alert" /><div><b>Rejected with a reason.</b> {l.reason}</div></div>
        )}
        {l.status === 'in_review' && (
          <div className="banner info"><Icon name="info" /><div>We will email <b>{PUB.contactEmail}</b> when the review is done. While it is in review the submission is locked.</div></div>
        )}
        <div className="card"><h2 style={{ marginBottom: 16 }}>Submission progress</h2><Timeline l={l} /></div>
        <div className="card">
          <h2 style={{ marginBottom: 16 }}>Connector details</h2>
          <dl className="kv">
            <div><dt>Domain</dt><dd>{PUB.domain}</dd></div>
            <div><dt>Public copy</dt><dd><span className="status ok">Verified</span><div className="small muted" style={{ overflowWrap: 'anywhere' }}>{`https://${PUB.domain}/.well-known/alexa-connector.json`}</div></dd></div>
            <div><dt>Category</dt><dd>Food &amp; drink</dd></div>
            <div><dt>Contact</dt><dd>{PUB.contactEmail}</dd></div>
            <div><dt>Endpoints</dt><dd>{TOOLS.length} · 1 write (payment), 2 read</dd></div>
            <div><dt>Account linking</dt><dd>OAuth 2.0 authorization code · PKCE {al.pkce ? 'on' : 'off'}</dd></div>
            <div><dt>Scopes</dt><dd>{al.scopes.map((s, i) => <span key={s}>{i ? ' ' : ''}<code>{s}</code></span>)}</dd></div>
            <div><dt>Service ID</dt><dd><code>{SERVICE_UUID}</code></dd></div>
            <div>
              <dt>MCP URL</dt>
              <dd>
                <code style={{ overflowWrap: 'anywhere' }}>{mcpUrl(SERVICE_UUID)}</code>
                <div className="small muted">
                  {l.status === 'approved' ? 'Goes live the first time a user publishes Demo Bistro.' : 'Reserved. Goes live after approval, the first time a user publishes Demo Bistro.'}
                  {' '}One URL for every user; the user token on each call picks whose account is used.
                </div>
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </>
  );
}

/* --------------------------------------------------------------- checks */
function ChecksTab() {
  const { latest: l } = useOwner();
  const toast = useToast();
  const [run, setRun] = useState(0);
  return (
    <>
      <div className="page-head">
        <div><h1>Automated checks</h1><p className="lede">Run on every upload and again at submission. All of them must pass before a reviewer sees the connector.</p></div>
        <div className="actions"><button className="btn btn-outline" onClick={() => setRun((r) => r + 1)}><Icon name="refresh" />Run again</button></div>
      </div>
      <div className="stack">
        <div className="row wrap">
          <span className="count-pill ok">8 of 8 checks passed</span>
          <span className="muted small">Last run {fmtDateTime(l.submitted)} · version {l.version}</span>
        </div>
        <div><CheckRunner report={l.report} run={run} onDone={() => toast('8 of 8 checks passed', 'ok')} /></div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- tools */
function ToolsTab() {
  return (
    <>
      <div className="page-head"><div><h1>Tools for Alexa+</h1><p className="lede">Each OpenAPI operation becomes one MCP tool. The name comes from operationId, inputSchema merges path, query and body parameters, and the annotations come from sideEffect. Write and payment tools always ask the user before they run.</p></div></div>
      <div className="stack">{TOOLS.map((t, i) => <ToolCard key={t.name} tool={t} open={i === 0} />)}</div>
    </>
  );
}

/* ------------------------------------------------------------- manifest */
function ManifestTab() {
  const { latest: l } = useOwner();
  const [view, setView] = useState('upload');
  // jsonHTML escapes every value, so this markup is safe to inject.
  const html = view === 'upload' ? jsonHTML(MANIFEST, { markPrivate: true }) : jsonHTML(hostedManifest());
  return (
    <>
      <div className="page-head">
        <div><h1>Manifest</h1><p className="lede">One JSON file: publisher, account linking, a private block for review only, and your OpenAPI spec with x-alexa fields on every endpoint.</p></div>
        <div className="actions"><a className="btn btn-outline" href={SAMPLE_MANIFEST} target="_blank" rel="noopener"><Icon name="download" />Download upload</a></div>
      </div>
      <div className="subtabs" role="tablist">
        <button role="tab" aria-selected={view === 'upload'} onClick={() => setView('upload')}>Uploaded file (version {l.version})</button>
        <button role="tab" aria-selected={view === 'hosted'} onClick={() => setView('hosted')}>Hosted copy at /.well-known</button>
      </div>
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </>
  );
}

/* -------------------------------------------------------------- linking */
function LinkingTab() {
  const al = MANIFEST.accountLinking;
  return (
    <>
      <div className="page-head"><div><h1>Account linking</h1><p className="lede">Alexa+ users sign in on your own login page. Amazon receives tokens, never passwords.</p></div></div>
      <div className="stack">
        <div className="banner info"><Icon name="shield" /><div><b>What MCP Bridge stores for each Alexa user:</b> the access token, its expiry, the refresh token and the granted scopes, encrypted in the token vault. Expired tokens are refreshed automatically. When a user unlinks, the token is revoked at your revocation URL and deleted from the vault.</div></div>
        <div className="card">
          <h2 style={{ marginBottom: 16 }}>OAuth 2.0 settings</h2>
          <dl className="kv">
            <div><dt>Grant type</dt><dd>Authorization code{al.pkce ? ' with PKCE (S256)' : ''}</dd></div>
            <div><dt>Client ID</dt><dd><code>{al.clientId}</code></dd></div>
            <div><dt>Authorization URL</dt><dd><code>{al.authorizationUrl}</code></dd></div>
            <div><dt>Token URL</dt><dd><code>{al.tokenUrl}</code></dd></div>
            <div><dt>Revocation URL</dt><dd><code>{al.revocationUrl}</code></dd></div>
            <div><dt>Token auth method</dt><dd><code>{al.tokenAuthMethod}</code></dd></div>
            <div><dt>Redirect URI (ours)</dt><dd><code>https://link.mcpbridge.dev/callback</code></dd></div>
            <div><dt>Client secret</dt><dd><span className="status ok">Stored in the secrets store</span><div className="small muted">From the private block · never hosted, never shown again</div></dd></div>
          </dl>
        </div>
        <div className="card">
          <h2 style={{ marginBottom: 6 }}>Scopes users are asked to grant</h2>
          <p className="muted" style={{ marginBottom: 14 }}>Shown on your consent screen and in the Alexa app before the user signs in.</p>
          {al.scopes.map((s) => (
            <div className="perm" key={s}>
              <span className="ic"><Icon name="check" cls="s" /></span>
              <div>{SCOPE_LABELS[s]}<span className="s"><code>{s}</code></span></div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------- submissions */
function SubmissionsTab() {
  const { submissions, latest } = useOwner();
  return (
    <>
      <div className="page-head">
        <div><h1>Submissions</h1><p className="lede">Every version you have submitted, with the reviewer's note when there is one.</p></div>
        {latest.status !== 'in_review' && <NewSubmissionButton />}
      </div>
      <div className="card pad-0"><div className="table-wrap">
        <table className="tbl cards">
          <thead><tr><th>Version</th><th>Submitted</th><th>Automated checks</th><th>Status</th><th>Reviewer note</th></tr></thead>
          <tbody>
            {submissions.map((s) => (
              <tr key={s.version + s.submitted.getTime()}>
                <td data-l="Version" className="primary tnum">{s.version}</td>
                <td data-l="Submitted">{fmtDateTime(s.submitted)}</td>
                <td data-l="Automated checks"><span className="status ok">8 of 8 passed</span></td>
                <td data-l="Status"><StatusLabel status={s.status} /></td>
                <td data-l="Reviewer note" style={{ maxWidth: 420 }}>
                  {s.reason ? s.reason : s.status === 'in_review' ? <span className="muted">Waiting for a reviewer</span> : <span className="muted">None</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div></div>
    </>
  );
}
