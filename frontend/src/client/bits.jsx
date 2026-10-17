import Icon from '../lib/Icon.jsx';
import { fmtDate } from '../lib/utils.js';

export function RwTag({ tool: t }) {
  if (t.sideEffect === 'payment') return <span className="tag payment">Write · charges your card</span>;
  if (t.read_only) return <span className="tag read">Read</span>;
  return <span className="tag write">Write</span>;
}

export function ToolList({ tools }) {
  return (
    <ul className="tool-list">
      {tools.map((t) => (
        <li key={t.name}><span><code>{t.name}</code><span className="d">{t.title}</span></span><RwTag tool={t} /></li>
      ))}
    </ul>
  );
}

// Square service logo with initials. `size` 44 or 48 in the sheets and publish screen.
export function SheetLogo({ s, size = 44 }) {
  return (
    <div className="logo" style={{ width: size, height: size, borderRadius: 12, background: s.color, color: '#fff', display: 'grid', placeContent: 'center', fontWeight: 700 }}>
      {s.initials}
    </div>
  );
}

export function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

export function lastCalledText(d) {
  if (!d) return 'Not called yet';
  const m = Math.round((Date.now() - d) / 60000);
  return 'Last called ' + (m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : fmtDate(d));
}
