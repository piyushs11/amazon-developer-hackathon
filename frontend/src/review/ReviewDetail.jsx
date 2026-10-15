import { useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { NavItems, Row2 } from '../components/ConsoleShell.jsx';
import { ChecksList } from '../components/ChecksList.jsx';
import CopyButton from '../components/CopyButton.jsx';
import { useOverlay } from '../components/Overlay.jsx';
import ToolCard, { SideEffectTag } from '../components/ToolCard.jsx';
import { useToast } from '../components/Toast.jsx';
import { mcpUrl } from '../data/manifest.js';
import Icon from '../lib/Icon.jsx';
import { jsonHTML } from '../lib/json.js';
import { fmtDate, fmtDateTime } from '../lib/utils.js';
import { ApproveDialog, RejectDialog } from './decisions.jsx';
import ReviewShell from './ReviewShell.jsx';
import { ChecksSummary, StatusLabel, isOpen, useReview } from './reviewState.jsx';
import TrySimulator from './TrySimulator.jsx';

const TABS = [
  ['summary', 'Summary', 'grid'],
  ['checks', 'Check report', 'shield'],
  ['tools', 'Generated tools', 'bolt'],
  ['linking', 'Account linking', 'key'],
  ['test', 'Test account', 'lock'],
  ['manifest', 'Manifest', 'file'],
  ['try', 'Try it', 'play'],
  ['history', 'History', 'history'],
];

export default function ReviewDetail() {
  const { id, tab } = useParams();
  const { find } = useReview();
  const overlay = useOverlay();
  const s = find(id);
  if (!s) return <Navigate to="/review" replace />;

  // Only submissions with a live test API can be tried in the simulator.
  const tabs = TABS.filter((t) => t[0] !== 'try' || s.tb);
  if (!tabs.some((t) => t[0] === tab)) return <Navigate to={`/review/${id}/summary`} replace />;

  const nav = (
    <NavItems items={[
      { section: 'Submission' },
      ...tabs.map((t) => ({ label: t[1], to: `/review/${id}/${t[0]}`, current: t[0] === tab, icon: t[2], count: t[0] === 'tools' ? s.tools.length : null })),
    ]} />
  );
  const row2 = (
    <Row2
      back={{ to: '/review', label: 'Queue' }}
      title={s.service + ' · v' + s.version}
      extra={<span className="title" style={{ fontWeight: 400, color: '#dbe7f0' }}><StatusLabel status={s.status} /></span>}
    />
  );

  const actions = isOpen(s) && (
    <div className="actions decision">
      <button className="btn btn-outline" onClick={() => overlay.open(<RejectDialog s={s} />)}>Reject</button>
      <button className="btn btn-primary" onClick={() => overlay.open(<ApproveDialog s={s} />)}><Icon name="check" />Approve</button>
    </div>
  );
  const head = (title, lede) => (
    <div className="page-head">
      <div><h1>{title}</h1>{lede && <p className="lede">{lede}</p>}</div>
      {actions}
    </div>
  );

  return (
    <ReviewShell row2={row2} nav={nav}>
      {tab === 'summary' && <>{head(s.service, s.description)}<Summary s={s} /></>}
      {tab === 'checks' && (
        <>
          {head('Check report', 'Automated checks run at upload and again at submission. Warnings are recommendations; failures block submission.')}
          <div className="stack">
            <div className="row wrap"><ChecksSummary report={s.report} /><span className="muted small">Run at submission · {fmtDateTime(s.submitted)}</span></div>
            <ChecksList report={s.report} />
          </div>
        </>
      )}
      {tab === 'tools' && (
        <>
          {head('Generated tools', 'What Alexa+ will register from this connector: one MCP tool per OpenAPI operation, with annotations from sideEffect. Write and payment tools always ask the customer first.')}
          <div className="stack">{s.tools.map((t, i) => <ToolCard key={t.name} tool={t} open={i === 0} />)}</div>
        </>
      )}
      {tab === 'linking' && <>{head('Account linking', "Customers sign in on the owner's login page. MCP Bridge stores tokens only.")}<Linking s={s} /></>}
      {tab === 'test' && <>{head('Test account', 'From the private block of the upload. Kept in the secrets store, never in the hosted copy.')}<TestAccount s={s} /></>}
      {tab === 'manifest' && (
        <>
          {head('Manifest', 'The uploaded file. The private block is shown here for review and nowhere else.')}
          {s.manifest
            ? <div dangerouslySetInnerHTML={{ __html: jsonHTML(s.manifest, { markPrivate: true }) }} />
            : <div className="banner info"><Icon name="info" /><div>Manifest preview is available for this submission in the full console build.</div></div>}
        </>
      )}
      {tab === 'try' && <>{head('Try it', "Signed in with the owner's test account. Ask what a customer would ask; every reply shows the tool it called.")}<TrySimulator s={s} /></>}
      {tab === 'history' && <>{head('History', 'Every version this domain has submitted.')}<History s={s} /></>}
    </ReviewShell>
  );
}

/* ---------------------------------------------------------------- summary */
const CHECKLIST = [
  "Signed in with the test account on the owner's login page",
  'Tried every tool in the simulator; replies make sense when spoken',
  'Payment and write tools ask first and say what will be charged',
  'Spoken replies contain no IDs, codes or JSON',
  'Privacy policy and terms open and cover account data',
];

function Summary({ s }) {
  const { startReview } = useReview();
  const toast = useToast();
  const al = s.linking;
  const prev = s.history[0];

  return (
    <div className="stack">
      {s.status === 'rejected' && (
        <div className="banner err"><Icon name="alert" /><div><b>Rejected {fmtDate(s.reviewed)} by {s.reviewer}.</b> {s.reason}</div></div>
      )}
      {s.status === 'approved' && (
        <div className="banner ok"><Icon name="check" /><div>
          <b>Approved {fmtDate(s.reviewed)} by {s.reviewer} and listed in the catalog.</b>{' '}
          {s.server
            ? `Live at ${mcpUrl(s.uuid)} since ${fmtDate(s.server.published)} · ${s.server.users} connected users.`
            : `Not published yet; its tools go live the first time a user publishes ${s.service}.`}
        </div></div>
      )}
      {s.status === 'pending' && (
        <div className="banner info">
          <Icon name="info" />
          <div className="grow"><b>Waiting for a reviewer.</b> Start the review to lock the submission and let the owner know it is being looked at.</div>
          <button className="btn btn-secondary btn-sm" onClick={() => { startReview(s.id); toast('Assigned to you · In review'); }}>Start review</button>
        </div>
      )}
      {prev && prev.status === 'rejected' && (
        <div className="banner warn"><Icon name="history" /><div><b>Resubmission.</b> Version {prev.version} was rejected {fmtDate(prev.reviewed)}: {prev.reason}</div></div>
      )}

      <div className="card">
        <h2 style={{ marginBottom: 16 }}>Submission</h2>
        <dl className="kv">
          <div><dt>Domain</dt><dd>{s.domain}</dd></div>
          <div><dt>Public copy</dt><dd><span className="status ok">Matches upload</span><div className="small muted" style={{ overflowWrap: 'anywhere' }}>{`https://${s.domain}/.well-known/alexa-connector.json`}</div></dd></div>
          <div><dt>Category</dt><dd>{s.category}</dd></div>
          <div><dt>Owner contact</dt><dd>{s.contact}</dd></div>
          <div><dt>Version</dt><dd className="tnum">{s.version}</dd></div>
          <div><dt>Submitted</dt><dd>{fmtDateTime(s.submitted)}</dd></div>
          <div><dt>Automated checks</dt><dd><ChecksSummary report={s.report} /></dd></div>
          <div><dt>Attachment</dt><dd>
            {s.pdf
              ? <a href="#" onClick={(e) => { e.preventDefault(); toast("Attachments open in the full console build. This demo doesn't store files."); }}><Icon name="pdf" cls="s" /> {s.pdf}</a>
              : <span className="muted">None</span>}
          </dd></div>
          <div><dt>Account linking</dt><dd>OAuth 2.0 authorization code{al.pkce ? ' · PKCE' : ''}<div className="small muted">{al.scopes.join(', ')}</div></dd></div>
        </dl>
        <div className="divider" style={{ margin: '18px 0' }}></div>
        <h3 style={{ marginBottom: 6 }}>Owner's version message</h3>
        <p className="muted">{s.message}</p>
      </div>

      <div className="card">
        <h2 style={{ marginBottom: 12 }}>{s.tools.length} tools Alexa+ will get</h2>
        <ul className="ep-list">
          {s.tools.map((t) => (
            <li key={t.name}><code>{t.name}</code><span className="muted">{t.title}</span><SideEffectTag sideEffect={t.sideEffect} /></li>
          ))}
        </ul>
      </div>

      <div className="card">
        <h2 style={{ marginBottom: 6 }}>Reviewer checklist</h2>
        <p className="muted" style={{ marginBottom: 14 }}>The parts the automated checks can't cover.</p>
        <ul className="cl">
          {CHECKLIST.map((c, i) => (
            <li key={c}><label className="check"><input type="checkbox" id={'cl' + i} /><span>{c}</span></label></li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- linking */
function Linking({ s }) {
  const al = s.linking;
  return (
    <div className="stack">
      <div className="banner info"><Icon name="shield" /><div><b>What MCP Bridge stores per Alexa user:</b> access token, expiry, refresh token and scopes, encrypted in the token vault. Never the customer's password. On unlink the token is revoked at the owner's revocation URL and deleted.</div></div>
      <div className="card">
        <h2 style={{ marginBottom: 16 }}>OAuth 2.0 settings</h2>
        <dl className="kv">
          <div><dt>Grant type</dt><dd>Authorization code{al.pkce ? ' with PKCE (S256)' : ''}</dd></div>
          <div><dt>Client ID</dt><dd><code>{al.clientId}</code></dd></div>
          <div><dt>Authorization URL</dt><dd><code style={{ overflowWrap: 'anywhere' }}>{al.authorizationUrl}</code></dd></div>
          <div><dt>Token URL</dt><dd><code style={{ overflowWrap: 'anywhere' }}>{al.tokenUrl}</code></dd></div>
          <div><dt>Revocation URL</dt><dd><code style={{ overflowWrap: 'anywhere' }}>{al.revocationUrl}</code></dd></div>
          <div><dt>Token auth method</dt><dd><code>{al.tokenAuthMethod}</code></dd></div>
          <div><dt>Client secret</dt><dd><span className="status ok">In the secrets store</span></dd></div>
          <div><dt>Scopes</dt><dd>{al.scopes.map((x, i) => <span key={x}>{i ? ' ' : ''}<code>{x}</code></span>)}</dd></div>
        </dl>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------- test account */
function TestAccount({ s }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="stack">
      <div className="card">
        <h2 style={{ marginBottom: 16 }}>Credentials</h2>
        <dl className="kv">
          <div><dt>Username</dt><dd className="secret"><code>{s.testAccount.username}</code><CopyButton value={s.testAccount.username} text="Copy" /></dd></div>
          <div><dt>Password</dt><dd className="secret">
            <code>{shown ? s.testAccount.password : '••••••••••••'}</code>
            <button className="btn btn-ghost btn-sm" onClick={() => setShown((v) => !v)}>
              <Icon name={shown ? 'eye-off' : 'eye'} cls="s" />{shown ? 'Hide' : 'Reveal'}
            </button>
          </dd></div>
          <div><dt>Login page</dt><dd><code style={{ overflowWrap: 'anywhere' }}>{s.linking.authorizationUrl}</code></dd></div>
        </dl>
        <div className="divider" style={{ margin: '18px 0' }}></div>
        <h3 style={{ marginBottom: 6 }}>Owner's notes for review</h3>
        <p className="muted">{s.reviewNotes || 'None provided.'}</p>
      </div>
      {s.tb && (
        <div className="card row between wrap">
          <div><h3>Try the tools with this account</h3><p className="muted">The simulator signs in as the test account and calls the generated tools against the owner's API.</p></div>
          <Link className="btn btn-primary" to={`/review/${s.id}/try`}><Icon name="play" />Open the simulator</Link>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- history */
function History({ s }) {
  const all = [{ version: s.version, submitted: s.submitted, reviewed: s.reviewed, status: s.status, reviewer: s.reviewer, reason: s.reason, current: true }, ...s.history];
  return (
    <div className="card pad-0"><div className="table-wrap">
      <table className="tbl cards">
        <thead><tr><th>Version</th><th>Submitted</th><th>Reviewed</th><th>Status</th><th>Reviewer note</th></tr></thead>
        <tbody>
          {all.map((h) => (
            <tr key={h.version}>
              <td className="primary tnum" data-l="Version">{h.version}{h.current && <> <span className="tag blue">This submission</span></>}</td>
              <td data-l="Submitted">{fmtDateTime(h.submitted)}</td>
              <td data-l="Reviewed">{h.reviewed ? fmtDateTime(h.reviewed) + ' · ' + (h.reviewer || '') : <span className="muted">Not yet</span>}</td>
              <td data-l="Status"><StatusLabel status={h.status} /></td>
              <td data-l="Reviewer note" style={{ maxWidth: 420 }}>{h.reason ? h.reason : <span className="muted">None</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div></div>
  );
}
