import { useEffect, useState } from 'react';
import { useToast } from '../components/Toast.jsx';
import { mcpUrl } from '../data/manifest.js';
import Icon from '../lib/Icon.jsx';
import { MENU, fill } from '../sim/demoBistro.js';
import { canSpeak, speak } from '../sim/speech.js';
import { useClient } from './clientState.jsx';
import { SLOTS } from './mockBackend.js';
import { RwTag } from './bits.jsx';

const isEnum = (p) => / \| /.test(p.type);

function initialValues(tool) {
  const v = {};
  tool.params.forEach((p) => {
    if (p.name === 'items') return;
    if (isEnum(p)) v[p.name] = p.default != null ? String(p.default) : p.required ? p.type.split(' | ')[0] : '';
    else v[p.name] = p.name === 'order_id' ? 'A1042' : p.name === 'query' ? 'wrap' : p.default != null ? String(p.default) : '';
  });
  return v;
}

// Tools mode: a plain MCP client against the service's MCP URL, with the user's token.
export default function ToolsPanel({ preset }) {
  const { backend, me, voiceOn, simMemory, rememberSim, closeLayer, goSearch } = useClient();
  const toast = useToast();
  const sim = simMemory(me.id);
  const usable = backend.publishedFor(me.id);
  const [uuid, setUuid] = useState(() => {
    if (preset && usable.includes(preset)) return preset;
    return usable.includes(sim.uuid) ? sim.uuid : usable[0] || null;
  });
  const defs = uuid ? backend.toolDefs(uuid) : [];
  const [toolName, setToolName] = useState(() => (uuid === sim.uuid ? sim.tool : null));
  const tool = defs.find((t) => t.name === toolName) || defs[0];
  const [results, setResults] = useState(sim.results);

  // Remember the selection per user across openings of the simulator.
  const currentTool = tool ? tool.name : null;
  useEffect(() => { rememberSim(me.id, { uuid, tool: currentTool }); }, [rememberSim, me.id, uuid, currentTool]);

  if (!uuid) {
    return (
      <div className="not-avail">
        <div className="ring"><Icon name="terminal" /></div>
        <h2>No published services yet</h2>
        <p className="muted">Connect and publish a service to call its tools here.</p>
        <button type="button" className="btn btn-primary" onClick={() => { closeLayer(); goSearch(); }}>Onboard a service</button>
      </div>
    );
  }

  const call = (args) => {
    const r = backend.gatewayCall(me.id, uuid, tool, args);
    const entry = { svc: backend.catalog[uuid].name, user: me.id, url: mcpUrl(uuid), ...r };
    const next = [entry, ...results];
    rememberSim(me.id, { results: next });
    setResults(next);
    if (voiceOn) speak(r.text);
  };

  const readAloud = (t) => {
    if (!canSpeak()) { toast("Speech isn't available in this browser.", 'err'); return; }
    speak(t);
  };

  return (
    <>
      <div className="field">
        <label htmlFor="tSvc">Service</label>
        <select className="select" id="tSvc" value={uuid} onChange={(e) => { setUuid(e.target.value); setToolName(null); }}>
          {usable.map((u) => <option value={u} key={u}>{backend.catalog[u].name}</option>)}
        </select>
      </div>
      <div className="conn">
        MCP client → <b>POST {mcpUrl(uuid)}</b><br />
        Authorization: Bearer •••• ({me.name}'s user token)<br />
        initialize <span className="ok">ok</span> · tools/list <span className="ok">{defs.length} tools</span>
      </div>
      <div className="tool-pick" role="group" aria-label="Tool" style={{ marginTop: 14 }}>
        {defs.map((t) => (
          <button type="button" className="chip" key={t.name} aria-pressed={t.name === tool.name} onClick={() => setToolName(t.name)}>{t.name}</button>
        ))}
      </div>

      <ToolForm key={uuid + ':' + tool.name} tool={tool} onCall={call} />

      <div className="section-h" style={{ paddingTop: 24 }}>Results</div>
      <div className="stack">
        {results.length ? results.slice(0, 6).map((r, i) => (
          <div className="res-card" key={results.length - i}>
            <div className="hd">
              <span>{r.tool} · {r.svc}</span>
              <span className={'status ' + (r.is_error ? 'err' : 'ok')} style={{ fontFamily: 'var(--font-text)', fontWeight: 400, fontSize: 13 }}>{r.is_error ? 'is_error' : 'ok'}</span>
            </div>
            <div className="rw"><span className="k">Arguments</span><pre>{JSON.stringify(r.arguments, null, 2)}</pre></div>
            <div className="rw"><span className="k">Gateway</span><pre>{'POST ' + r.url + '\nuser_id: ' + r.user + ' (from the user token)'}</pre></div>
            <div className="rw"><span className="k">Upstream</span><pre>{r.request ? r.request.method + ' ' + r.request.url + '\n→ ' + r.status : 'Not called'}</pre></div>
            <div className="rw">
              <span className="k">Alexa says</span>
              <div className="row" style={{ alignItems: 'flex-start', gap: 8 }}>
                <span className="ans grow">{r.text}</span>
                <button type="button" className="btn-icon btn sm" aria-label="Read aloud" onClick={() => readAloud(r.text)}><Icon name="speaker" cls="s" /></button>
              </div>
            </div>
          </div>
        )) : (
          <p className="empty">Each call shows the tool, its arguments, which user the gateway resolved, the request sent to the service, and the answer Alexa would speak.</p>
        )}
      </div>
    </>
  );
}

function ToolForm({ tool, onCall }) {
  const toast = useToast();
  const hasItems = tool.params.some((p) => p.name === 'items');
  const [values, setValues] = useState(() => initialValues(tool));
  const [dishes, setDishes] = useState(() => (hasItems ? [{ name: 'Paneer Tikka Wrap', qty: 1 }] : []));
  const [prompt, setPrompt] = useState(null);

  const collect = () => {
    const a = { ...values };
    if (hasItems) a.items = dishes.map((d) => ({ item_name: d.name, quantity: parseInt(d.qty, 10) || 1 }));
    return a;
  };
  const run = () => { onCall(collect()); setPrompt(null); };
  const setDish = (i, patch) => setDishes((list) => list.map((d, j) => (j === i ? { ...d, ...patch } : d)));

  // Write tools never run without a yes, just like Alexa+ asks before acting.
  const submit = (e) => {
    e.preventDefault();
    if (tool.read_only) { run(); return; }
    const a = collect();
    setPrompt(fill(tool.confirm || 'Should I go ahead?', {
      fulfillment: a.fulfillment || 'delivery',
      slot: (SLOTS.find((s) => s.id === a.slot_id) || {}).label || 'that time',
      party_size: a.party_size,
      time: a.time,
    }));
  };

  return (
    <form className="tform" onSubmit={submit}>
      <div className="row wrap" style={{ gap: 8 }}><b>{tool.title}</b><RwTag tool={tool} /></div>
      {tool.params.length ? tool.params.map((p) => {
        const id = 'f_' + p.name;
        const label = <label htmlFor={id}>{p.name}<span className="opt">{p.in}{p.required ? '' : ' · optional'}</span></label>;
        const hint = p.description ? <div className="hint">{p.description}</div> : null;
        if (p.name === 'items') {
          return (
            <div className="field" key={p.name}>
              {label}{hint}
              <div className="stack-s">
                {dishes.map((d, i) => (
                  <div className="dish-row" key={i}>
                    <select className="select" aria-label="Dish" value={d.name} onChange={(e) => setDish(i, { name: e.target.value })}>
                      {MENU.map((m) => <option key={m.id}>{m.name}</option>)}
                    </select>
                    <input className="input" type="number" min="1" max="10" value={d.qty} aria-label="Quantity" onChange={(e) => setDish(i, { qty: e.target.value })} />
                  </div>
                ))}
              </div>
              <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => setDishes((l) => [...l, { name: 'Mango Lassi', qty: 1 }])}>
                <Icon name="plus" />Add a dish
              </button>
            </div>
          );
        }
        const onChange = (e) => setValues((v) => ({ ...v, [p.name]: e.target.value }));
        if (isEnum(p)) {
          return (
            <div className="field" key={p.name}>
              {label}{hint}
              <select className="select" id={id} value={values[p.name]} onChange={onChange}>
                {!p.required && <option value="">(none)</option>}
                {p.type.split(' | ').map((o) => <option key={o}>{o}</option>)}
              </select>
            </div>
          );
        }
        const numeric = p.type === 'integer';
        return (
          <div className="field" key={p.name}>
            {label}{hint}
            <input className="input" id={id} type={numeric ? 'number' : 'text'} min={numeric ? 1 : undefined} value={values[p.name]} onChange={onChange} autoComplete="off" />
          </div>
        );
      }) : <p className="muted small">This tool takes no arguments.</p>}

      {/* Always present so the form spacing matches with or without a pending confirmation. */}
      <div>
        {prompt && (
          <div className={'ask-first' + (tool.sideEffect === 'payment' ? '' : ' write')}>
            <b>Write tool. Alexa asks first:</b> "{prompt}"
            <div className="row">
              <button type="button" className="btn btn-primary btn-sm" onClick={run}>Yes</button>
              <button type="button" className="btn btn-outline btn-sm" onClick={() => { setPrompt(null); toast('Not called. Nothing changed.', '', 2000); }}>No</button>
            </div>
          </div>
        )}
      </div>

      <button type="submit" className="btn btn-primary btn-lg"><Icon name="play" />tools/call {tool.name}</button>
    </form>
  );
}
