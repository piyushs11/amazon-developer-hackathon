import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { Row2 } from '../components/ConsoleShell.jsx';
import { CheckRunner } from '../components/ChecksList.jsx';
import { SideEffectTag } from '../components/ToolCard.jsx';
import ToolCard from '../components/ToolCard.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { checkReport } from '../data/checks.js';
import { MANIFEST } from '../data/manifest.js';
import { TOOLS } from '../data/tools.js';
import OwnerShell from './OwnerShell.jsx';
import { useOwner } from './ownerState.jsx';

const STEPS = ['Upload manifest', 'Automated checks', 'Tool preview', 'Submit for review'];

export default function Wizard() {
  const { step: stepParam } = useParams();
  const { owner, wizard: w, resetWizard } = useOwner();
  const requested = parseInt(stepParam, 10) || 1;

  // After a submission the wizard starts over the next time it is opened.
  useEffect(() => { if (w.submitted) resetWizard(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A step can only be reached once the earlier ones are done.
  let step = requested;
  if (!w.submitted) {
    if (step > 1 && !w.file) step = 1;
    if (step > 2 && !w.done) step = 2;
  }
  if (step < 1 || step > 4) step = 1;
  if (step !== requested) return <Navigate to={'/owner/submit/' + step} replace />;

  const nav = (
    <>
      <div className="sect">Steps</div>
      {STEPS.map((label, i) => <StepNavButton key={label} n={i + 1} label={label} step={step} />)}
    </>
  );

  return (
    <OwnerShell row2={<Row2 back={{ to: '/owner/demobistro/overview', label: owner.name }} title="New submission" />} nav={nav}>
      {step === 1 && <StepUpload />}
      {step === 2 && <StepChecks />}
      {step === 3 && <StepTools />}
      {step === 4 && <StepSubmit />}
    </OwnerShell>
  );
}

function StepNavButton({ n, label, step }) {
  const { wizard: w } = useOwner();
  const navigate = useNavigate();
  const reachable = (n === 2 && w.file) || (n === 3 && w.done) || (n === 4 && w.done);
  const ok = (n === 1 && w.file) || (n === 2 && w.done) || (n === 3 && w.done && step > 3);
  const disabled = n > step && !reachable;
  return (
    <button
      type="button"
      aria-current={n === step ? 'page' : undefined}
      disabled={disabled}
      onClick={() => { if (!disabled) navigate('/owner/submit/' + n); }}
    >
      {ok && n !== step ? <Icon name="check" cls="s step-ok" /> : <span className="tnum" style={{ width: 16, textAlign: 'center' }}>{n}</span>}
      {label}
    </button>
  );
}

function WizFoot({ left, children }) {
  return <div className="wiz-foot">{left}<div className="right">{children}</div></div>;
}

/* ------------------------------------------------------- 1. upload */
function StepUpload() {
  const { owner, wizard: w, patchWizard } = useOwner();
  const toast = useToast();
  const navigate = useNavigate();
  const [over, setOver] = useState(false);
  const fileIn = useRef(null);
  const pdfIn = useRef(null);

  function acceptFile(f) {
    if (!/\.json$/i.test(f.name)) { toast('Choose a .json manifest file.', 'err'); return; }
    const r = new FileReader();
    r.onload = () => {
      try {
        const j = JSON.parse(r.result);
        if (!j.manifestVersion || !j.publisher || !j.openapi) throw new Error('shape');
        patchWizard({ file: { name: f.name, size: f.size, manifest: j }, done: false });
      } catch {
        toast("That file isn't a connector manifest. It needs manifestVersion, publisher, accountLinking and openapi.", 'err', 6000);
      }
    };
    r.readAsText(f);
  }

  const useSample = (e) => {
    e.stopPropagation();
    patchWizard({ file: { name: 'alexa-connector.upload.json', size: 9668, manifest: MANIFEST }, done: false });
  };

  return (
    <>
      <div className="page-head"><div>
        <h1>Upload the connector manifest</h1>
        <p className="lede">One JSON file for {owner.domain}: your OpenAPI spec with x-alexa fields, account linking, and a private block with the client secret and a test account for the reviewer.</p>
      </div></div>
      <div className="stack">
        <div
          className={'dropzone' + (over ? ' over' : '')}
          hidden={!!w.file}
          tabIndex={0}
          role="button"
          aria-label="Choose the manifest file"
          onClick={(e) => { if (e.target.id !== 'useSample') fileIn.current.click(); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileIn.current.click(); } }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) acceptFile(e.dataTransfer.files[0]); }}
        >
          <Icon name="upload" />
          <div><b>Drop alexa-connector.upload.json here</b> or click to choose a file</div>
          <div className="small muted" style={{ marginTop: 4 }}>JSON · up to 2 MB</div>
          <div style={{ marginTop: 12 }}>
            <button type="button" className="btn btn-secondary btn-sm" id="useSample" onClick={useSample}>Use the sample manifest</button>
          </div>
        </div>
        <input type="file" ref={fileIn} accept="application/json,.json" hidden
          onChange={(e) => { if (e.target.files[0]) acceptFile(e.target.files[0]); e.target.value = ''; }} />

        {/* always rendered, like the prototype's #parsed container, so the stack spacing matches */}
        <div>{w.file && <ParsedManifest file={w.file} onRemove={() => patchWizard({ file: null, done: false })} />}</div>

        <div className="field">
          <label>Notes for the reviewer (PDF, optional)</label>
          <div className="hint">Anything that helps the review, such as screenshots of your login page or how to use the test account.</div>
          <div>
            {w.pdf ? (
              <div className="row wrap">
                <span className="filechip"><Icon name="pdf" /><span className="name">{w.pdf.name}</span><span className="muted small">{(w.pdf.size / 1024).toFixed(0)} KB</span></span>
                <button className="btn btn-ghost btn-sm" onClick={() => patchWizard({ pdf: null })}>Remove</button>
              </div>
            ) : (
              <div className="row wrap">
                <button className="btn btn-outline btn-sm" onClick={() => pdfIn.current.click()}><Icon name="clip" />Attach PDF</button>
              </div>
            )}
          </div>
          <input type="file" ref={pdfIn} accept="application/pdf,.pdf" hidden
            onChange={(e) => { const f = e.target.files[0]; if (f) patchWizard({ pdf: { name: f.name, size: f.size } }); e.target.value = ''; }} />
        </div>
      </div>
      <WizFoot left={<Link className="btn btn-ghost" to="/owner/demobistro/overview">Cancel</Link>}>
        <button className="btn btn-primary" disabled={!w.file} onClick={() => navigate('/owner/submit/2')}>Run automated checks <Icon name="arrow-right" /></button>
      </WizFoot>
    </>
  );
}

function ParsedManifest({ file: f, onRemove }) {
  const mf = f.manifest, pub = mf.publisher || {}, al = mf.accountLinking || {};
  const ops = [];
  Object.keys((mf.openapi && mf.openapi.paths) || {}).forEach((p) =>
    Object.keys(mf.openapi.paths[p]).forEach((mt) => ops.push(mf.openapi.paths[p][mt])));
  return (
    <div className="card stack">
      <div className="row wrap between">
        <span className="filechip"><Icon name="file" /><span className="name">{f.name}</span><span className="muted small">{(f.size / 1024).toFixed(1)} KB</span></span>
        <button className="btn btn-ghost btn-sm" onClick={onRemove}>Remove</button>
      </div>
      <dl className="kv">
        <div><dt>Publisher</dt><dd>{pub.name}</dd></div>
        <div><dt>Domain</dt><dd>{pub.domain}</dd></div>
        <div><dt>Category</dt><dd>{(pub.category || '').replace(/_/g, ' ')}</dd></div>
        <div><dt>Contact</dt><dd>{pub.contactEmail}</dd></div>
        <div>
          <dt>Account linking</dt>
          <dd>{al.type === 'oauth2_authorization_code' ? 'OAuth 2.0 authorization code' : al.type}{al.pkce ? ' · PKCE' : ''}<div className="small muted">{(al.scopes || []).join(', ')}</div></dd>
        </div>
        <div>
          <dt>Private block</dt>
          <dd><span className="status warn">Upload only</span><div className="small muted">clientSecret, testAccount, reviewNotes are stripped from the hosted copy and kept in the secrets store.</div></dd>
        </div>
      </dl>
      <div>
        <h3 style={{ marginBottom: 8 }}>{ops.length} endpoints → {ops.length} MCP tools</h3>
        <ul className="ep-list">
          {ops.map((o) => (
            <li key={o.operationId}>
              <code>{o.operationId}</code><span className="muted">{o.summary || ''}</span>
              <SideEffectTag sideEffect={(o['x-alexa'] || {}).sideEffect || 'none'} />
            </li>
          ))}
        </ul>
      </div>
      <div className="banner info"><Icon name="globe" /><div>Before running the checks, host this file without the private block at <b>{`https://${pub.domain}/.well-known/alexa-connector.json`}</b>. That is how we verify you own the domain and how users find you by website.</div></div>
    </div>
  );
}

/* ------------------------------------------------------- 2. checks */
function StepChecks() {
  const { owner, wizard: w, patchWizard } = useOwner();
  const navigate = useNavigate();
  const [report] = useState(checkReport);
  // If the checks already passed, show them as done instead of replaying the animation.
  const [alreadyDone] = useState(w.done);

  return (
    <>
      <div className="page-head"><div>
        <h1>Automated checks</h1>
        <p className="lede">Eight checks run against the upload and the public copy on {owner.domain}. They must all pass before you can submit.</p>
      </div></div>
      <div className="stack">
        <div>
          {w.done ? (
            <>
              <div className="row wrap"><span className="count-pill ok">8 of 8 checks passed</span></div>
              <div className="banner ok" style={{ marginTop: 12 }}><Icon name="check" /><div><b>Your connector is ready for submission.</b> Once submitted, we run the checks one last time and an Amazon reviewer takes a look.</div></div>
            </>
          ) : (
            <div className="row wrap"><span className="count-pill" style={{ background: 'var(--fill-2)', color: 'var(--fg-2)' }}>Running checks...</span></div>
          )}
        </div>
        <div><CheckRunner report={report} run={alreadyDone ? 0 : 1} onDone={() => patchWizard({ done: true })} /></div>
      </div>
      <WizFoot left={<Link className="btn btn-ghost" to="/owner/submit/1"><Icon name="arrow-left" />Previous</Link>}>
        <button className="btn btn-primary" disabled={!w.done} onClick={() => navigate('/owner/submit/3')}>Preview tools <Icon name="arrow-right" /></button>
      </WizFoot>
    </>
  );
}

/* ------------------------------------------------------- 3. tools */
function StepTools() {
  const navigate = useNavigate();
  return (
    <>
      <div className="page-head"><div>
        <h1>Tools Alexa+ will get</h1>
        <p className="lede">Generated from your OpenAPI spec. Check the phrases people will say and what Alexa says back; this is also what the reviewer sees.</p>
      </div></div>
      <div className="stack">{TOOLS.map((t, i) => <ToolCard key={t.name} tool={t} open={i === 1} />)}</div>
      <WizFoot left={<Link className="btn btn-ghost" to="/owner/submit/2"><Icon name="arrow-left" />Previous</Link>}>
        <button className="btn btn-primary" onClick={() => navigate('/owner/submit/4')}>Continue to submit <Icon name="arrow-right" /></button>
      </WizFoot>
    </>
  );
}

/* ------------------------------------------------------- 4. submit */
function StepSubmit() {
  const { owner, wizard: w, patchWizard, submit } = useOwner();
  const toast = useToast();
  const navigate = useNavigate();

  const onSubmit = () => {
    const version = submit();
    toast('Version ' + version + ' submitted for review', 'ok');
    navigate('/owner/demobistro/overview');
  };

  return (
    <>
      <div className="page-head"><div>
        <h1>Submit for review</h1>
        <p className="lede">An Amazon reviewer checks the report and tool preview, then signs in with your test account and tries the tools. You'll get an email with the result.</p>
      </div></div>
      <div className="stack">
        <div className="card">
          <h2 style={{ marginBottom: 14 }}>What you're submitting</h2>
          <ul className="summary-list">
            <li><Icon name="check" cls="s" /><span><b>alexa-connector.upload.json</b> for {owner.domain} · 3 endpoints · OAuth 2.0 with PKCE</span></li>
            <li><Icon name="check" cls="s" /><span>Public copy hosted at <code>{`https://${owner.domain}/.well-known/alexa-connector.json`}</code> and matching, private block excluded</span></li>
            <li><Icon name="check" cls="s" /><span>8 of 8 automated checks passed</span></li>
            <li><Icon name="check" cls="s" /><span>place_order (write, payment) asks the user for a spoken yes before it runs</span></li>
            {w.pdf && <li><Icon name="check" cls="s" /><span>Reviewer notes attached: <b>{w.pdf.name}</b></span></li>}
          </ul>
        </div>
        <div className="card stack">
          <div className="field" style={{ maxWidth: 220 }}>
            <label htmlFor="ver">Version</label>
            <input className="input" id="ver" value={w.version} onChange={(e) => patchWizard({ version: e.target.value })} />
          </div>
          <div className="field">
            <label htmlFor="msg">Version message</label>
            <div className="hint">What changed since the last submission. The reviewer sees this.</div>
            <textarea className="textarea" id="msg" maxLength={300} placeholder="e.g. Fixed the test account password; added example phrases for search_menu"
              value={w.message} onChange={(e) => patchWizard({ message: e.target.value })} />
            <div className="counter"><span>{w.message.length}</span>/300 characters</div>
          </div>
          <label className="check">
            <input type="checkbox" id="confirmTA" checked={w.confirm} onChange={(e) => patchWizard({ confirm: e.target.checked })} />
            <span>The test account in the private block signs in at auth.{owner.domain} and will stay active until the review is done.</span>
          </label>
        </div>
      </div>
      <WizFoot left={<Link className="btn btn-ghost" to="/owner/submit/3"><Icon name="arrow-left" />Previous</Link>}>
        <button className="btn btn-primary" disabled={!w.confirm} onClick={onSubmit}>Submit for review</button>
      </WizFoot>
    </>
  );
}
