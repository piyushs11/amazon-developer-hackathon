import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useToast } from '../components/Toast.jsx';
import { mcpUrl } from '../data/manifest.js';
import Icon from '../lib/Icon.jsx';
import { useClient } from './clientState.jsx';
import { DB, PUBLISH_STAGES } from './mockBackend.js';
import { SheetLogo, ToolList } from './bits.jsx';

// S2c: POST /publish and follow its progress. Generation is skipped when another user already
// published the service, since bundles are built once per service.
export default function PublishScreen({ uuid }) {
  const { backend, me, closeLayer, openPublish, openSim } = useClient();
  const navigate = useNavigate();
  const toast = useToast();
  const s = backend.catalog[uuid];
  const [publishedVersion] = useState(() => backend.registry(uuid).version);
  const [phase, setPhase] = useState('idle'); // idle | running | done | failed
  const [steps, setSteps] = useState(null);
  const [skipped, setSkipped] = useState(false);
  const [failNote, setFailNote] = useState('');
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const STEP_INFO = [
    ['Generating', 'One tool file per endpoint, from ' + s.name + "'s spec"],
    ['Deploying', 'Loading the bundle into the MCP gateway and marking it active'],
    ['Registering', 'Adding the MCP URL to Alexa+'],
  ];

  const publish = async () => {
    setPhase('running');
    let current = -1;
    const res = await backend.publish(me.id, uuid, (stage) => {
      if (!mounted.current) return;
      if (stage === 'skipped') { setSkipped(true); setSteps(['done', 'done', 'done']); return; }
      current = PUBLISH_STAGES.indexOf(stage);
      setSteps(PUBLISH_STAGES.map((_, i) => (i < current ? 'done' : i === current ? 'run' : '')));
    });
    if (!mounted.current) return;
    if (res.status === 'failed') {
      setSteps(PUBLISH_STAGES.map((_, i) => (i < current ? 'done' : i === current ? 'fail' : '')));
      setFailNote(res.error.step + ' · ' + res.error.code);
      setPhase('failed');
      return;
    }
    setSteps(['done', 'done', 'done']);
    setPhase('done');
  };

  const toServices = () => { closeLayer(); navigate('/client/services'); };

  return (
    <div className="full">
      <div className="inner">
        <div className="app-top">
          <button type="button" className="btn-icon btn" aria-label="Close" onClick={closeLayer}><Icon name="x" /></button>
          <div className="title">Publish</div>
          <span style={{ width: 38 }}></span>
        </div>
        <div className="app-body" style={{ paddingBottom: 24, overflow: 'auto' }}>
          <div className="app-sheet-head">
            <SheetLogo s={s} size={48} />
            <div><h2 style={{ margin: 0 }}>{s.name}</h2><div className="muted small">Connected as {me.email}</div></div>
          </div>
          <div className="section-h">Tools</div>
          <ToolList tools={s.tools} />
          <div className="progress-note" style={{ marginTop: 0 }}>
            {publishedVersion
              ? `${s.name} is already published (version ${publishedVersion}). Publishing adds it to your Alexa+ right away, at the same MCP URL everyone uses.`
              : `First publish for ${s.name}. We generate its tools once and serve them at one MCP URL for everyone. Each call uses the caller's own account.`}
            <span className="mcp" style={{ marginTop: 6 }}>{mcpUrl(uuid)}</span>
          </div>

          <div style={{ marginTop: 20 }}>
            {steps && (
              <ul className="progress-steps">
                {STEP_INFO.map(([label, desc], i) => {
                  const st = steps[i] || '';
                  const sub = st === 'fail' ? failNote : st === 'done' && skipped ? 'Already done for ' + s.name + ' · skipped' : desc;
                  return (
                    <li key={label} className={st}>
                      <span className="ic"><Icon name={st === 'fail' ? 'x' : 'check'} /></span>
                      <span>{label}<span className="s">{sub}</span></span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div style={{ marginTop: 18 }}>
            {phase === 'idle' && (
              <button type="button" className="btn btn-primary btn-lg btn-block" onClick={publish}><Icon name="bolt" />Publish</button>
            )}
            {phase === 'running' && <p className="small muted" style={{ textAlign: 'center' }}>Publishing...</p>}
            {phase === 'failed' && (
              <>
                <div className="banner err"><Icon name="alert" /><div><b>Publish failed while deploying.</b> The new bundle didn't load in the gateway, so nothing went live. Your {s.name} connection is saved.</div></div>
                <div className="stack-s" style={{ marginTop: 14 }}>
                  <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => openPublish(uuid)}><Icon name="refresh" />Retry</button>
                  <button type="button" className="btn btn-secondary btn-lg btn-block" onClick={toServices}>Back to Services</button>
                </div>
              </>
            )}
            {phase === 'done' && (
              <>
                <div className="banner ok"><Icon name="check" /><div><b>{s.name} is live on Alexa+.</b> MCP URL: <span className="mcp" style={{ display: 'inline' }}>{mcpUrl(uuid)}</span></div></div>
                <div className="stack-s" style={{ marginTop: 14 }}>
                  <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => { toServices(); toast(s.name + ' published', 'ok'); }}>Back to Services</button>
                  <button type="button" className="btn btn-secondary btn-lg btn-block" onClick={() => { toServices(); openSim(uuid === DB ? { send: 'What is the status of order A1042' } : { mode: 'tools', uuid }); }}>Try it in the simulator</button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
