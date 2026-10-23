import { useState } from 'react';
import ResultCard from '../components/ResultCard.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import { fill } from '../lib/templates.js';
import { canSpeak, speak } from '../sim/speech.js';
import { useReview } from './reviewState.jsx';

// Try a submission's tools against the owner's real API, signed in with the test account from
// its private block (POST /api/review/submissions/{id}/try). Nothing is published.
export default function TrySimulator({ s }) {
  const { tryTool } = useReview();
  const toast = useToast();
  const [toolName, setToolName] = useState(s.tools[0]?.name);
  const tool = s.tools.find((t) => t.name === toolName) || s.tools[0];
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);

  const call = async (args) => {
    setBusy(true);
    try {
      const r = await tryTool(s.id, tool.name, args);
      setResults((list) => [r, ...list]);
    } catch (e) {
      toast(e.message, 'err', 6000);
    } finally {
      setBusy(false);
    }
  };

  if (!tool) return <p className="muted">This submission has no tools.</p>;
  return (
    <div className="stack">
      <div className="sim-head">
        <div className="who"><Icon name="lock" cls="s" /><span>Signed in as</span><b>{s.testAccount?.username}</b><span className="tag read">test account</span></div>
      </div>
      <div className="tool-pick" role="group" aria-label="Tool">
        {s.tools.map((t) => (
          <button type="button" className="chip" key={t.name} aria-pressed={t.name === tool.name} onClick={() => setToolName(t.name)}>{t.name}</button>
        ))}
      </div>
      <TryForm key={tool.name} tool={tool} onCall={call} busy={busy} />
      {results.map((r, i) => (
        <ResultCard
          key={results.length - i}
          title={r.tool}
          ok={!r.is_error}
          text={r.text}
          onSpeak={() => (canSpeak() ? speak(r.text) : toast("Speech isn't available in this browser.", 'err'))}
          rows={[
            { label: 'Request', value: r.request.method + ' ' + r.request.url + '\n→ ' + r.status + ' · as ' + r.account },
            { label: 'Response data', value: JSON.stringify(r.data, null, 2) },
          ]}
        />
      ))}
    </div>
  );
}

function TryForm({ tool, onCall, busy }) {
  const [values, setValues] = useState(() => Object.fromEntries(tool.params.map((p) => [p.name, tool.exampleArgs[p.name] != null ? String(tool.exampleArgs[p.name]) : ''])));
  const [prompt, setPrompt] = useState(null);
  const args = () => Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ''));

  const submit = (e) => {
    e.preventDefault();
    if (tool.read_only) onCall(args());
    else setPrompt(fill(tool.confirmationPrompt || 'Should I go ahead?', args()));
  };

  return (
    <form className="card stack" onSubmit={submit}>
      <div><b>{tool.title}</b><div className="small muted">{tool.http.method} {tool.http.baseUrl + tool.http.path}</div></div>
      {tool.params.map((p) => (
        <div className="field" key={p.name}>
          <label htmlFor={'try_' + p.name}>{p.name} <span className="muted small">{p.in}{p.required ? '' : ' · optional'}</span></label>
          {p.description && <div className="hint">{p.description}</div>}
          <input className="input" id={'try_' + p.name} type={p.type === 'integer' || p.type === 'number' ? 'number' : 'text'}
            value={values[p.name]} onChange={(e) => setValues((v) => ({ ...v, [p.name]: e.target.value }))} autoComplete="off" />
        </div>
      ))}
      {!tool.params.length && <p className="muted small">This tool takes no arguments.</p>}
      {prompt && (
        <div className="ask-first write">
          <b>Write tool. Alexa asks first:</b> "{prompt}"
          <div className="row">
            <button type="button" className="btn btn-primary btn-sm" onClick={() => { onCall(args()); setPrompt(null); }}>Yes</button>
            <button type="button" className="btn btn-outline btn-sm" onClick={() => setPrompt(null)}>No</button>
          </div>
        </div>
      )}
      <div><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Calling...' : 'Call ' + tool.name}</button></div>
    </form>
  );
}
