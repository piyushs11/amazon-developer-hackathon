import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import Icon from '../lib/Icon.jsx';

// Shared console chrome used by the Owner Portal and the Review Console:
// dark two-row header (brand + right side, then breadcrumb/tabs), grey side nav, white content.
export default function ConsoleShell({ brandTo, subtitle, right, row2, nav, children }) {
  const { pathname } = useLocation();

  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);

  return (
    <div className="console">
      <header className="chead">
        <div className="chead-row1">
          <Link className="brand" to={brandTo}>
            <span className="mark"><Icon name="bridge" /></span>MCP Bridge<span className="sub">{subtitle}</span>
          </Link>
          <span className="spacer"></span>
          {right}
        </div>
        <div className="chead-row2">{row2}</div>
      </header>
      <div className="cbody">
        <nav className="cnav" aria-label="Section">{nav}</nav>
        <main className="cmain">{children}</main>
      </div>
    </div>
  );
}

// Side-nav entries. Items are { section } headings or { label, to | href, current, icon, count }.
export function NavItems({ items }) {
  return items.map((it, i) => {
    if (it.section) return <div className="sect" key={i}>{it.section}</div>;
    const inner = (
      <>
        {it.icon && <Icon name={it.icon} cls={'s ' + (it.iconCls || '')} />}
        {it.label}
        {it.count != null && <span className="cnt">{it.count}</span>}
      </>
    );
    const cur = it.current ? { 'aria-current': 'page' } : {};
    return it.to
      ? <Link key={i} to={it.to} {...cur}>{inner}</Link>
      : <a key={i} href={it.href} {...(it.ext ? { target: '_blank', rel: 'noopener' } : {})} {...cur}>{inner}</a>;
  });
}

// Second header row: optional back link, title and anything extra.
export function Row2({ back, title, extra }) {
  return (
    <>
      {back && (
        <Link className="back" to={back.to}><Icon name="chevron-left" cls="s" />{back.label}</Link>
      )}
      <span className="title">{title}</span>
      {extra}
    </>
  );
}
