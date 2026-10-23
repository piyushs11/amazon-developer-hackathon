import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';
import { Row2 } from '../components/ConsoleShell.jsx';
import { CheckRunner } from '../components/ChecksList.jsx';
import { SideEffectTag } from '../components/ToolCard.jsx';
import ToolCard from '../components/ToolCard.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { checksLabel, toolCards } from '../lib/portal.js';
import OwnerShell from './OwnerShell.jsx';
import { bump, useConnector, useOwner } from './ownerState.jsx';

const STEPS = ['Upload manifest', 'Automated checks', 'Tool preview', 'Submit for review'];
const MAX_PDF = 5 * 1024 * 1024;

export default function Wizard() {
  const { step: stepParam } = useParams();
  const { wizard: w, connectors } = useOwner();
  const requested = parseInt(stepParam, 10) || 1;
  const target = w.target ? (connectors || []).find((c) => c.service_uuid === w.target) : null;

  // A step can only be reached once the earlier ones are done.
  let step = requested;
  if (step > 1 && !w.file) step = 1;
  if (step > 2 && !w.report?.passed) step = 2;
  if (step < 1 || step > 4) step = 1;
  if (w.submitted) step = 1;
  if (step !== requested) return <Navigate to={'/owner/submit/' + step} replace />;

  const nav = (
    <>
      <div className="sect">Steps</div>
      {STEPS.map((label, i) => <StepNavButton key={label} n={i + 1} label={label} step={step} />)}
    </>
  );
  const back = target ? { to: `/owner/${target.service_uuid}/overview`, label: target.service_name } : { to: '/owner', label: 'Your connectors' };

  return (
    <OwnerShell row2={<Row2 back={back} title="New submission" />} nav={nav}>
      {step === 1 && <StepUpload back={back} />}
      {step === 2 && <StepChecks />}
      {step === 3 && <StepTools />}
      {step === 4 && <StepSubmit />}
    </OwnerShell>
  );
}

function StepNavButton({ n, label, step }) {
  const { wizard: w } = useOwner();
  const navigate = useNavigate();
  const passed = !!w.report?.passed;
  const reachable = (n === 2 && w.file) || (n === 3 && passed) || (n === 4 && passed);
  const ok = (n === 1 && w.file) || (n === 2 && passed) || (n === 3 && passed && step > 3);
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
function StepUpload({ back }) {
  const { wizard: w, patchWizard } = useOwner();
  const { connector } = useConnector(w.target);
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
        patchWizard({ file: { name: f.name, size: f.size, manifest: JSON.parse(r.result) }, report: null });
      } catch {
        toast("That file isn't valid JSON.", 'err', 6000);
      }
    };
    r.readAsText(f);
  }

  // Start from the version that is in the catalog now (or the latest one sent).
  const current = connector?.latest?.manifest;
  const useCurrent = (e) => {
    e.stopPropagation();
    const text = JSON.stringify(current, null, 2);
    patchWizard({ file: { name: `${connector.domain}-${connector.latest.version}.json`, size: text.length, manifest: JSON.parse(text) }, report: null });
  };

  return (
    <>
      <div className="page-head"><div>
        <h1>Upload the connector manifest</h1>
        <p className="lede">One JSON file: your OpenAPI spec with x-alexa fields (example phrases, confirmation prompts, what Alexa says), account linking, and a private block with a test account for the reviewer.</p>
      </div></div>
      <div className="stack">
        <div
          className={'dropzone' + (over ? ' over' : '')}
          hidden={!!w.file}
          tabIndex={0}
          role="button"
          aria-label="Choose the manifest file"
          onClick={(e) => { if (e.target.id !== 'useCurrent') fileIn.current.click(); }}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileIn.current.click(); } }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) acceptFile(e.dataTransfer.files[0]); }}
        >
          <Icon name="upload" />
          <div><b>Drop your manifest .json here</b> or click to choose a file</div>
          <div className="small muted" style={{ marginTop: 4 }}>JSON · up to 2 MB</div>
          {current && (
            <div style={{ marginTop: 12 }}>
              <button type="button" className="btn btn-secondary btn-sm" id="useCurrent" onClick={useCurrent}>Start from version {connector.latest.version}</button>
            </div>
          )}
        </div>
        <input type="file" ref={fileIn} accept="application/json,.json" hidden data-testid="manifest-input"
          onChange={(e) => { if (e.target.files[0]) acceptFile(e.target.files[0]); e.target.value = ''; }} />

        <div>{w.file && <ParsedManifest file={w.file} onRemove={() => patchWizard({ file: null, report: null })} />}</div>

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
            onChange={(e) => {
              const f = e.target.files[0];
              if (f && f.size > MAX_PDF) toast('PDFs up to 5 MB.', 'err');
              else if (f) patchWizard({ pdf: { name: f.name, size: f.size, file: f } });
              e.target.value = '';
            }} />
        </div>
      </div>
      <WizFoot left={<Link className="btn btn-ghost" to={back.to}>Cancel</Link>}>
        <button className="btn btn-primary" disabled={!w.file} onClick={() => navigate('/owner/submit/2')}>Run automated checks <Icon name="arrow-right" /></button>
      </WizFoot>
    </>
  );
}

function ParsedManifest({ file: f, onRemove }) {
  const mf = f.manifest || {}, pub = mf.publisher || {}, al = mf.accountLinking || {};
  const ops = [];
  Object.keys(mf.openapi?.paths || {}).forEach((p) =>
    Object.keys(mf.openapi.paths[p] || {}).forEach((mt) => ops.push(mf.openapi.paths[p][mt])));
  return (
    <div className="card stack">
      <div className="row wrap between">
        <span className="filechip"><Icon name="file" /><span className="name">{f.name}</span><span className="muted small">{(f.size / 1024).toFixed(1)} KB</span></span>
        <button className="btn btn-ghost btn-sm" onClick={onRemove}>Remove</button>
      </div>
      <dl className="kv">
        <div><dt>Publisher</dt><dd>{pub.name || <span className="muted">missing</span>}</dd></div>
        <div><dt>Domain</dt><dd>{pub.domain || <span className="muted">missing</span>}</dd></div>
        <div><dt>Category</dt><dd>{pub.category}{pub.city ? ' · ' + pub.city : ''}</dd></div>
        <div><dt>Version</dt><dd className="tnum">{mf.openapi?.info?.version || <span className="muted">missing</span>}</dd></div>
        <div>
          <dt>Account linking</dt>
          <dd>{al.type === 'oauth2_authorization_code' ? 'OAuth 2.0 authorization code' : al.type}{al.pkce ? ' · PKCE' : ''}<div className="small muted">{(al.scopes || []).join(', ')}</div></dd>
        </div>
        <div>
          <dt>Private block</dt>
          <dd><span className="status warn">Upload only</span><div className="small muted">clientSecret, testAccount and reviewNotes are never part of the hosted copy.</div></dd>
        </div>
      </dl>
      <div>
        <h3 style={{ marginBottom: 8 }}>{ops.length} endpoints → {ops.length} MCP tools</h3>
        <ul className="ep-list">
          {ops.map((o, i) => (
            <li key={(o.operationId || '') + i}>
              <code>{o.operationId || '(no operationId)'}</code><span className="muted">{o.summary || ''}</span>
              <SideEffectTag sideEffect={(o['x-alexa'] || {}).sideEffect || 'none'} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ------------------------------------------------------- 2. checks */
function StepChecks() {
  const { wizard: w, patchWizard, runChecks } = useOwner();
  const navigate = useNavigate();
  const toast = useToast();
  const [run, setRun] = useState(w.report ? 0 : null);
  const [animated, setAnimated] = useState(!!w.report);

  // POST /api/owner/checks once per upload, then replay the results one by one.
  useEffect(() => {
    if (w.report) return;
    let live = true;
    runChecks(w.file.manifest)
      .then((report) => { if (live) { patchWizard({ report }); setRun(1); } })
      .catch((e) => { if (live) toast(e.message, 'err'); });
    return () => { live = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const report = w.report;
  const label = report && checksLabel(report);
  return (
    <>
      <div className="page-head"><div>
        <h1>Automated checks</h1>
        <p className="lede">Eight checks run against the upload. Failures must be fixed before you can submit; warnings mark what only the local demo allows (http on mock hosts, demo domains).</p>
      </div></div>
      <div className="stack">
        <div>
          {!report || !animated ? (
            <div className="row wrap"><span className="count-pill" style={{ background: 'var(--fill-2)', color: 'var(--fg-2)' }}>Running checks...</span></div>
          ) : report.passed ? (
            <>
              <div className="row wrap"><span className={'count-pill ' + label.cls}>{label.text}</span></div>
              <div className="banner ok" style={{ marginTop: 12 }}><Icon name="check" /><div><b>Your connector is ready for submission.</b> Once submitted, we run the checks one last time and an Amazon reviewer takes a look.</div></div>
            </>
          ) : (
            <>
              <div className="row wrap"><span className="count-pill err">{label.text}</span></div>
              <div className="banner err" style={{ marginTop: 12 }}><Icon name="alert" /><div><b>Fix the failed checks and upload the manifest again.</b></div></div>
            </>
          )}
        </div>
        {report && <div><CheckRunner report={report} run={run || 0} onDone={() => setAnimated(true)} /></div>}
      </div>
      <WizFoot left={<Link className="btn btn-ghost" to="/owner/submit/1"><Icon name="arrow-left" />Previous</Link>}>
        <button className="btn btn-primary" disabled={!report?.passed || !animated} onClick={() => navigate('/owner/submit/3')}>Preview tools <Icon name="arrow-right" /></button>
      </WizFoot>
    </>
  );
}

/* ------------------------------------------------------- 3. tools */
function StepTools() {
  const { wizard: w } = useOwner();
  const navigate = useNavigate();
  const tools = toolCards(w.report, w.file.manifest);
  return (
    <>
      <div className="page-head"><div>
        <h1>Tools Alexa+ will get</h1>
        <p className="lede">Generated from your OpenAPI spec. Check the phrases people will say and what Alexa says back; this is also what the reviewer sees.</p>
      </div></div>
      <div className="stack">{tools.map((t, i) => <ToolCard key={t.name} tool={t} open={i === 0} />)}</div>
      <WizFoot left={<Link className="btn btn-ghost" to="/owner/submit/2"><Icon name="arrow-left" />Previous</Link>}>
        <button className="btn btn-primary" onClick={() => navigate('/owner/submit/4')}>Continue to submit <Icon name="arrow-right" /></button>
      </WizFoot>
    </>
  );
}

/* ------------------------------------------------------- 4. submit */
function StepSubmit() {
  const { wizard: w, patchWizard, submit, connectors } = useOwner();
  const toast = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const pub = w.file.manifest.publisher || {};
  const tools = w.report.tools || [];
  const writes = tools.filter((t) => !t.read_only);
  const label = checksLabel(w.report);
  // Default to the file's version, or the next one if that version was already sent.
  const taken = new Set(((connectors || []).find((c) => c.domain === pub.domain)?.submissions || []).map((s) => s.version));
  const fileVersion = w.report.version || '1.0';
  const suggested = taken.has(fileVersion) ? bump([...taken].sort().pop()) : fileVersion;
  const version = w.version || suggested;

  const onSubmit = async () => {
    setBusy(true);
    try {
      const row = await submit(version);
      toast('Version ' + row.version + ' submitted for review', 'ok');
      navigate(`/owner/${row.service_uuid}/overview`);
    } catch (e) {
      toast(e.message, 'err', 6000);
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head"><div>
        <h1>Submit for review</h1>
        <p className="lede">An Amazon reviewer checks the report and tool preview, then tries the tools against your API with your test account. You'll get an email with the result.</p>
      </div></div>
      <div className="stack">
        <div className="card">
          <h2 style={{ marginBottom: 14 }}>What you're submitting</h2>
          <ul className="summary-list">
            <li><Icon name="check" cls="s" /><span><b>{w.file.name}</b> for {pub.domain} · {tools.length} endpoints · OAuth 2.0</span></li>
            <li><Icon name="check" cls="s" /><span>Automated checks: {label.text}</span></li>
            {writes.length > 0 && <li><Icon name="check" cls="s" /><span>{writes.map((t) => t.name).join(', ')} ask the user for a spoken yes before they run</span></li>}
            {w.pdf && <li><Icon name="check" cls="s" /><span>Reviewer notes attached: <b>{w.pdf.name}</b></span></li>}
          </ul>
        </div>
        <div className="card stack">
          <div className="field" style={{ maxWidth: 220 }}>
            <label htmlFor="ver">Version</label>
            <input className="input" id="ver" value={version} onChange={(e) => patchWizard({ version: e.target.value })} />
            {taken.size > 0 && <div className="hint">Already sent: {[...taken].join(', ')}</div>}
          </div>
          <div className="field">
            <label htmlFor="msg">Version message</label>
            <div className="hint">What changed since the last submission. The reviewer sees this.</div>
            <textarea className="textarea" id="msg" maxLength={300} placeholder="e.g. Added order tracking"
              value={w.message} onChange={(e) => patchWizard({ message: e.target.value })} />
            <div className="counter"><span>{w.message.length}</span>/300 characters</div>
          </div>
          <label className="check">
            <input type="checkbox" id="confirmTA" checked={w.confirm} onChange={(e) => patchWizard({ confirm: e.target.checked })} />
            <span>The test account in the private block signs in on our login page and will stay active until the review is done.</span>
          </label>
        </div>
      </div>
      <WizFoot left={<Link className="btn btn-ghost" to="/owner/submit/3"><Icon name="arrow-left" />Previous</Link>}>
        <button className="btn btn-primary" disabled={!w.confirm || busy} onClick={onSubmit}>{busy ? 'Submitting...' : 'Submit for review'}</button>
      </WizFoot>
    </>
  );
}
