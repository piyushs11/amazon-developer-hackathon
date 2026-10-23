import Icon from '../lib/Icon.jsx';

// One tool call result, shared by the Alexa+ Tools mode and the review console's Try it:
// the answer Alexa would speak first, the technical request details tucked into a <details>.
//   title   what was called ("search_menu · Demo Bistro")
//   ok      false shows the "Error" status
//   text    the spoken answer
//   onSpeak optional; shows a "Read aloud" button
//   rows    [{ label, value }] shown (monospace) under "Request details"
export default function ResultCard({ title, ok, text, onSpeak, rows = [] }) {
  return (
    <article className="res-card">
      <header className="hd">
        <span className="who">{title}</span>
        <span className={'status ' + (ok ? 'ok' : 'err')}>{ok ? 'OK' : 'Error'}</span>
      </header>
      <div className="ans-row">
        <p className="ans">{text || 'No spoken answer.'}</p>
        {onSpeak && (
          <button type="button" className="btn-icon btn plain sm" aria-label="Read aloud" onClick={onSpeak}>
            <Icon name="speaker" cls="s" />
          </button>
        )}
      </div>
      {rows.length > 0 && (
        <details className="req">
          <summary>Request details</summary>
          {rows.map((r) => (
            <div className="rw" key={r.label}>
              <span className="k">{r.label}</span>
              <pre>{r.value}</pre>
            </div>
          ))}
        </details>
      )}
    </article>
  );
}
