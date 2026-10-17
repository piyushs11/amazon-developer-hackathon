import { useEffect, useRef, useSyncExternalStore } from 'react';
import Icon from '../lib/Icon.jsx';
import { money } from '../lib/utils.js';

function AlexaExtra({ extra, session, onNeedLink }) {
  if (!extra) return null;
  if (extra.type === 'items') {
    const items = extra.items;
    return (
      <div className="card-list">
        {items.slice(0, 5).map((m) => (
          <div className="item" key={m.id}>
            <div>{m.name}<span className="sub">{m.category}{m.sold_out ? ' · sold out today' : ''}</span></div>
            <div className="price">{money(m.price_cents)}</div>
          </div>
        ))}
        {items.length > 5 && <div className="meta">and {items.length - 5} more</div>}
      </div>
    );
  }
  if (extra.type === 'receipt') return <div className="meta">Demo Bistro will email your receipt.</div>;
  if (extra.type === 'confirm') {
    return (
      <div className="confirm-row">
        <button className="btn btn-primary" type="button" onClick={() => session.send('Yes')}>Yes</button>
        <button className="btn btn-outline" type="button" onClick={() => session.send('No')}>No</button>
      </div>
    );
  }
  if (extra.type === 'link' && onNeedLink) {
    return (
      <div className="confirm-row">
        <button className="btn btn-secondary" type="button" onClick={onNeedLink}>Open Services</button>
      </div>
    );
  }
  return null;
}

// Renders a chat session: the conversation log plus the suggestion chips.
export default function ChatView({ session, showTrace = true, onNeedLink, hidden }) {
  const snap = useSyncExternalStore(session.subscribe, session.getSnapshot);
  const logRef = useRef(null);

  useEffect(() => {
    const id = requestAnimationFrame(() => {
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    });
    return () => cancelAnimationFrame(id);
  }, [snap.items, showTrace, hidden]);

  return (
    <div className="chat grow" hidden={hidden}>
      <div className="chat-log" aria-live="polite" ref={logRef}>
        {snap.items.map((it) => {
          if (it.kind === 'stamp') return <div className="chat-stamp" key={it.id}>{it.text}</div>;
          if (it.kind === 'user') return <div className="msg user" key={it.id}>{it.text}</div>;
          if (it.kind === 'thinking') return <div className="thinking" key={it.id}><i></i><i></i><i></i></div>;
          if (it.kind === 'trace') {
            if (!showTrace) return null;
            return (
              <div className="trace" key={it.id}>
                <div className="hd">
                  <Icon name="bolt" /><b>{it.tool}</b> · Demo Bistro · {it.ms} ms{' '}
                  {it.isError ? <span className="err">is_error</span> : <span className="ok">ok</span>}
                </div>
                {it.lines.map((l) => <div className="ln" key={l}>{l}</div>)}
              </div>
            );
          }
          return (
            <div className="msg alexa" key={it.id}>
              {it.text}
              <AlexaExtra extra={it.extra} session={session} onNeedLink={onNeedLink} />
            </div>
          );
        })}
      </div>
      <div className="suggest">
        {snap.suggestions.map((s) => (
          <button type="button" key={s} onClick={() => session.send(s)}>{s}</button>
        ))}
      </div>
    </div>
  );
}
