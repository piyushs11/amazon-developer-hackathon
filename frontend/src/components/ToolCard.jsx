import Icon from '../lib/Icon.jsx';

export function SideEffectTag({ sideEffect }) {
  if (sideEffect === 'payment') return <span className="tag payment">Write · payment · asks first</span>;
  if (sideEffect === 'write') return <span className="tag write">Write · asks first</span>;
  return <span className="tag read">Read</span>;
}

// One generated MCP tool: HTTP call, phrases, input schema, annotations and spoken replies.
export default function ToolCard({ tool: t, open }) {
  const ro = t.read_only != null ? t.read_only : t.sideEffect === 'none';
  return (
    <details className="tool" open={open}>
      <summary>
        <span className="name">{t.name}</span>
        <span className="title">{t.title}</span>
        <SideEffectTag sideEffect={t.sideEffect} />
        <Icon name="chevron-down" cls="chev" />
      </summary>
      <div className="body">
        <div>
          <div className="http"><b>{t.http.method}</b> {t.http.baseUrl + t.http.path}</div>
          <p style={{ marginTop: 6 }}>{t.description}</p>
        </div>
        <div>
          <h4>Users say</h4>
          <ul className="phrases">{t.examplePhrases.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
        <div>
          <h4>input_schema (path, query and body merged, required first)</h4>
          <div className="table-wrap">
            <table className="params">
              <thead><tr><th>Field</th><th>From</th><th>Type</th><th>Description</th></tr></thead>
              <tbody>
                {t.params.map((p) => (
                  <tr key={p.name}>
                    <td><code>{p.name}</code>{p.required ? '' : <> <span className="muted small">optional</span></>}</td>
                    <td>{p.in}</td>
                    <td>{p.type}</td>
                    <td>{p.description || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <h4>read_only and MCP tool annotations</h4>
          <div className="annot">
            <span className={ro ? 'on' : ''}>read_only: {String(ro)}</span>
            {Object.keys(t.annotations).map((k) => (
              <span key={k} className={t.annotations[k] ? 'on' : ''}>{k}: {String(t.annotations[k])}</span>
            ))}
          </div>
        </div>
        {t.requiresConfirmation && (
          <div className="speak"><span className="lbl">Alexa asks before calling</span>{t.confirmationPrompt}</div>
        )}
        <div className="speak"><span className="lbl">Alexa says on success</span>{t.speakableResponse}</div>
        {t.emptyResponse && (
          <div className="speak"><span className="lbl">When nothing is found</span>{t.emptyResponse}</div>
        )}
        {Object.keys(t.errorResponses).map((c) => (
          <div className="speak" key={c}><span className="lbl">On HTTP {c}</span>{t.errorResponses[c]}</div>
        ))}
      </div>
    </details>
  );
}
