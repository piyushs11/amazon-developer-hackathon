// Builds the highlighted manifest viewer markup. Every value is HTML-escaped first,
// so it is safe to render with dangerouslySetInnerHTML.
import { esc } from './utils.js';

export function jsonHTML(obj, opts) {
  opts = opts || {};
  const lines = JSON.stringify(obj, null, 2).split('\n');
  let inPriv = false, depth = 0, html = '';
  lines.forEach((ln) => {
    const open = ln.match(/^(\s*)"private": \{$/);
    let out = esc(ln)
      .replace(/^(\s*)(&quot;[^&]+&quot;)(:)/, '$1<span class="k">$2</span>$3')
      .replace(/: (&quot;.*&quot;)(,?)$/, ': <span class="s">$1</span>$2')
      .replace(/: (-?\d+(\.\d+)?|true|false|null)(,?)$/, ': <span class="n">$1</span>$3');
    if (open && opts.markPrivate) { inPriv = true; depth = open[1].length; out += ' <span class="priv-lbl">// upload only, stripped from the hosted copy</span>'; }
    if (inPriv) {
      html += '<span class="priv">' + out + '</span>';
      if (ln.match(new RegExp('^\\s{' + depth + '}\\},?$'))) inPriv = false;
    } else html += out + '\n';
  });
  return '<pre class="json">' + html + '</pre>';
}
