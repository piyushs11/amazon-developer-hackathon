import { useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router-dom';
import { NavItems, Row2 } from '../components/ConsoleShell.jsx';
import { CheckRunner } from '../components/ChecksList.jsx';
import ToolCard from '../components/ToolCard.jsx';
import { useToast } from '../components/Toast.jsx';
import { mcpUrl } from '../data/manifest.js';
import { API_URL } from '../lib/config.js';
import Icon from '../lib/Icon.jsx';
import { jsonHTML } from '../lib/json.js';
import { checksLabel, hostedCopy, toolCards, writeSummary } from '../lib/portal.js';
import { fmtDateTime } from '../lib/utils.js';
import OwnerShell, { GUIDE_PDF } from './OwnerShell.jsx';
import { StatusLabel, useConnector, useOwner } from './ownerState.jsx';

const TABS = [
  ['overview', 'Overview', 'grid'],
  ['checks', 'Automated checks', 'shield'],
  ['tools', 'Tools for Alexa+', 'bolt'],
  ['manifest', 'Manifest', 'file'],
  ['linking', 'Account linking', 'key'],
  ['submissions', 'Submissions', 'history'],
];

export default function ConnectorDetail() {
  const { uuid, tab } = useParams();
  const { connector: c, missing } = useConnector(uuid);
  if (missing) return <Navigate to="/owner" replace />;
  if (!TABS.some((t) => t[0] === tab)) return <Navigate to={`/owner/${uuid}/overview`} replace />;

  const nav = (
    <NavItems items={[
      { section: 'Connector' },
      ...TABS.map((t) => ({ label: t[1], to: `/owner/${uuid}/${t[0]}`, current: t[0] === tab, icon: t[2] })),
      { section: 'Resources' },
      { label: 'Owner submission guide (PDF)', href: GUIDE_PDF, ext: true, icon: 'pdf' },
    ]} />
  );
  const row2 = (
    <Row2
      back={{ to: '/owner', label: 'Your connectors' }}
      title={c ? c.service_name : ''}
      extra={c && <span className="title" style={{ fontWeight: 400, color: '#dbe7f0' }}><StatusLabel status={c.status} /></span>}
    />
  );

  return (
    <OwnerShell row2={row2} nav={nav}>
      {!c && <p className="muted">Loading...</p>}
      {c && !c.latest && <p className="muted">No submission yet.</p>}
      {c?.latest && tab === 'overview' && <Overview c={c} />}
      {c?.latest && tab === 'checks' && <ChecksTab c={c} />}
      {c?.latest && tab === 'tools' && <ToolsTab c={c} />}
      {c?.latest && tab === 'manifest' && <ManifestTab c={c} />}
      {c?.latest && tab === 'linking' && <LinkingTab c={c} />}
      {c && tab === 'submissions' && <SubmissionsTab c={c} />}
    </OwnerShell>
  );
}

const isOpen = (s) => s && (s.status === 'pending' || s.status === 'in_review');

function NewSubmissionButton({ c }) {
  const { resetWizard } = useOwner();
  const navigate = useNavigate();
  if (isOpen(c.latest)) return null;
  return (
    <div className="actions">
      <button className="btn btn-primary" onClick={() => { resetWizard(c.service_uuid); navigate('/owner/submit/1'); }}>
        <Icon name="plus" />New submission
      </button>
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

function Timeline({ l, name }) {
  const counts = checksLabel(l.check_report);
  const open = isOpen(l);
  return (
    <ol className="timeline">
      <Step cls="done" title="Submitted" desc={'Version ' + l.version + ' · ' + fmtDateTime(l.submitted)} ic="check" />
      <Step cls="done" title="Automated checks passed" desc={counts.text} ic="check" />
      {open && (<>
        <Step cls="now" title={l.status === 'in_review' ? 'In review' : 'Waiting for a reviewer'} desc="An Amazon reviewer reads the check report and tool preview, then tries the tools against your API with your test account." />
        <Step cls="todo" title="Approved" desc={name + ' is listed in the catalog. Its tools are generated once and go live at its MCP URL the first time a user publishes it.'} />
      </>)}
      {l.status === 'rejected' && (<>
        <Step cls="done" title="In review" desc={'Reviewed ' + fmtDateTime(l.reviewed)} ic="check" />
        <Step cls="fail" title="Rejected" desc="See the reason above. Fix it and submit a new version; the checks run again automatically." ic="x" />
      </>)}
      {l.status === 'approved' && (<>
        <Step cls="done" title="In review" desc={'Reviewed ' + fmtDateTime(l.reviewed)} ic="check" />
        <Step cls="done" title="Approved" desc="Listed in the Alexa+ catalog." ic="check" />
      </>)}
    </ol>
  );
}

function Overview({ c }) {
  const l = c.latest;
  const m = l.manifest;
  const pub = m.publisher || {};
  const al = m.accountLinking || {};
  const tools = toolCards(l.check_report, m);
  const hosted = (l.check_report.checks || []).find((x) => x.id === 'hosted');
  const live = c.live;
  return (
    <>
      <div className="page-head">
        <div><h1>Overview</h1><p className="lede">{pub.description}</p></div>
        <NewSubmissionButton c={c} />
      </div>
      <div className="stack">
        <div className="card status-card">
          <div>
            <div className="small muted" style={{ marginBottom: 6 }}>Connector status</div>
            <StatusLabel status={c.status} big />
          </div>
          <div className="last">
            <div><b>LAST SUBMITTED</b>{fmtDateTime(l.submitted)} · version {l.version}</div>
            {l.reviewed
              ? <div><b>REVIEWED</b>{fmtDateTime(l.reviewed)}</div>
              : <div><b>REVIEW</b>Waiting for an Amazon reviewer</div>}
          </div>
        </div>
        {l.status === 'rejected' && (
          <div className="banner err"><Icon name="alert" /><div><b>Rejected with a reason.</b> {l.reason}</div></div>
        )}
        {l.status === 'approved' && l.note && (
          <div className="banner ok"><Icon name="check" /><div><b>Reviewer note:</b> {l.note}</div></div>
        )}
        {isOpen(l) && (
          <div className="banner info"><Icon name="info" /><div>We will email <b>{pub.contactEmail || l.owner?.email}</b> when the review is done. While it is in review the submission is locked.</div></div>
        )}
        <div className="card"><h2 style={{ marginBottom: 16 }}>Submission progress</h2><Timeline l={l} name={c.service_name} /></div>
        <div className="card">
          <h2 style={{ marginBottom: 16 }}>Connector details</h2>
          <dl className="kv">
            <div><dt>Domain</dt><dd>{c.domain}</dd></div>
            <div><dt>Public copy</dt><dd>
              <span className={'status ' + (hosted?.status || '')}>{hosted?.status === 'ok' ? 'Verified' : hosted?.status === 'warn' ? 'Skipped (demo domain)' : 'Not verified'}</span>
              <div className="small muted" style={{ overflowWrap: 'anywhere' }}>{`https://${c.domain}/.well-known/alexa-connector.json`}</div>
            </dd></div>
            <div><dt>Category</dt><dd>{pub.category || '-'}{pub.city ? ' · ' + pub.city : ''}</dd></div>
            <div><dt>Contact</dt><dd>{pub.contactEmail || '-'}</dd></div>
            <div><dt>Endpoints</dt><dd>{writeSummary(tools)}</dd></div>
            <div><dt>Account linking</dt><dd>OAuth 2.0 authorization code{al.pkce ? ' · PKCE on' : ''}</dd></div>
            <div><dt>Scopes</dt><dd>{(al.scopes || []).map((s, i) => <span key={s}>{i ? ' ' : ''}<code>{s}</code></span>)}</dd></div>
            <div><dt>Service ID</dt><dd><code>{c.service_uuid}</code></dd></div>
            <div>
              <dt>MCP URL</dt>
              <dd>
                <code style={{ overflowWrap: 'anywhere' }}>{mcpUrl(c.service_uuid)}</code>
                <div className="small muted">
                  {live?.published
                    ? `Live: version ${live.version} · ${live.connected_users} connected user${live.connected_users === 1 ? '' : 's'}.`
                    : live ? 'Approved. Goes live the first time a user publishes it.' : 'Reserved. Goes live after approval, the first time a user publishes it.'}
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
function ChecksTab({ c }) {
  const { runChecks } = useOwner();
  const toast = useToast();
  const [report, setReport] = useState(c.latest.check_report);
  const [run, setRun] = useState(0);
  const [when, setWhen] = useState(c.latest.submitted);
  const again = async () => {
    try {
      const fresh = await runChecks(c.latest.manifest);
      setReport(fresh);
      setWhen(new Date());
      setRun((r) => r + 1);
    } catch (e) {
      toast(e.message, 'err');
    }
  };
  const label = checksLabel(report);
  return (
    <>
      <div className="page-head">
        <div><h1>Automated checks</h1><p className="lede">Run on every upload and again at submission. Failures block submission; warnings mark what only the local demo allows.</p></div>
        <div className="actions"><button className="btn btn-outline" onClick={again}><Icon name="refresh" />Run again</button></div>
      </div>
      <div className="stack">
        <div className="row wrap">
          <span className={'count-pill ' + label.cls}>{label.text}</span>
          <span className="muted small">Last run {fmtDateTime(when)} · version {c.latest.version}</span>
        </div>
        <div><CheckRunner report={report} run={run} onDone={() => toast(label.text, label.cls === 'err' ? 'err' : 'ok')} /></div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- tools */
function ToolsTab({ c }) {
  const tools = toolCards(c.latest.check_report, c.latest.manifest);
  return (
    <>
      <div className="page-head"><div><h1>Tools for Alexa+</h1><p className="lede">Each OpenAPI operation becomes one MCP tool. The name comes from operationId, inputSchema merges path, query and body parameters, and the annotations come from sideEffect. Write and payment tools always ask the user before they run.</p></div></div>
      <div className="stack">{tools.map((t, i) => <ToolCard key={t.name} tool={t} open={i === 0} />)}</div>
    </>
  );
}

/* ------------------------------------------------------------- manifest */
function ManifestTab({ c }) {
  const l = c.latest;
  const [view, setView] = useState('upload');
  // jsonHTML escapes every value, so this markup is safe to inject.
  const html = view === 'upload' ? jsonHTML(l.manifest, { markPrivate: true }) : jsonHTML(hostedCopy(l.manifest));
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(l.manifest, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${c.domain}-${l.version}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <div className="page-head">
        <div><h1>Manifest</h1><p className="lede">One JSON file: publisher, account linking, a private block for review only, and your OpenAPI spec with x-alexa fields on every endpoint.</p></div>
        <div className="actions"><button className="btn btn-outline" onClick={download}><Icon name="download" />Download upload</button></div>
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
function LinkingTab({ c }) {
  const al = c.latest.manifest.accountLinking || {};
  const labels = al.scopeLabels || c.profile?.scope_labels || {};
  return (
    <>
      <div className="page-head"><div><h1>Account linking</h1><p className="lede">Alexa+ users sign in on your own login page. Amazon receives tokens, never passwords.</p></div></div>
      <div className="stack">
        <div className="banner info"><Icon name="shield" /><div><b>What MCP Bridge stores for each Alexa user:</b> the access token, its expiry, the refresh token and the granted scopes, encrypted in the token vault. Expired tokens are refreshed automatically. When a user disconnects, the token is deleted from the vault.</div></div>
        <div className="card">
          <h2 style={{ marginBottom: 16 }}>OAuth 2.0 settings</h2>
          <dl className="kv">
            <div><dt>Grant type</dt><dd>Authorization code{al.pkce ? ' with PKCE (S256)' : ''}</dd></div>
            <div><dt>Client ID</dt><dd><code>{al.clientId}</code></dd></div>
            <div><dt>Authorization URL</dt><dd><code>{al.authorizationUrl}</code></dd></div>
            <div><dt>Token URL</dt><dd><code>{al.tokenUrl}</code></dd></div>
            {al.revocationUrl && <div><dt>Revocation URL</dt><dd><code>{al.revocationUrl}</code></dd></div>}
            <div><dt>Token auth method</dt><dd><code>{al.tokenAuthMethod}</code></dd></div>
            <div><dt>Redirect URI (ours)</dt><dd><code>{(API_URL || window.location.origin) + '/oauth/callback'}</code></dd></div>
            <div><dt>Client secret</dt><dd><span className="status ok">From the private block</span><div className="small muted">Never hosted, never shown again</div></dd></div>
          </dl>
        </div>
        <div className="card">
          <h2 style={{ marginBottom: 6 }}>Scopes users are asked to grant</h2>
          <p className="muted" style={{ marginBottom: 14 }}>Shown on your consent screen and in the Alexa app before the user signs in.</p>
          {(al.scopes || []).map((s) => (
            <div className="perm" key={s}>
              <span className="ic"><Icon name="check" cls="s" /></span>
              <div>{labels[s] || s}<span className="s"><code>{s}</code></span></div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------- submissions */
function SubmissionsTab({ c }) {
  return (
    <>
      <div className="page-head">
        <div><h1>Submissions</h1><p className="lede">Every version you have submitted, with the reviewer's note when there is one.</p></div>
        {c.latest && <NewSubmissionButton c={c} />}
      </div>
      <div className="card pad-0"><div className="table-wrap">
        <table className="tbl cards">
          <thead><tr><th>Version</th><th>Submitted</th><th>Automated checks</th><th>Status</th><th>Reviewer note</th></tr></thead>
          <tbody>
            {c.submissions.map((s) => {
              const ok = s.checks.ok + s.checks.warn;
              return (
                <tr key={s.id}>
                  <td data-l="Version" className="primary tnum">{s.version}</td>
                  <td data-l="Submitted">{fmtDateTime(s.submitted)}</td>
                  <td data-l="Automated checks"><span className={'status ' + (s.checks.err ? 'err' : 'ok')}>{ok} of {s.checks.total} passed</span></td>
                  <td data-l="Status"><StatusLabel status={s.status} /></td>
                  <td data-l="Reviewer note" style={{ maxWidth: 420 }}>
                    {s.reason || s.note || (isOpen(s) ? <span className="muted">Waiting for a reviewer</span> : <span className="muted">None</span>)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div></div>
    </>
  );
}
