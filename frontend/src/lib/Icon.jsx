import { ICON_PATHS } from './iconPaths.js';

// Same markup as the prototype's icon(name, cls): <svg class="i {cls}">.
export default function Icon({ name, cls }) {
  const d = ICON_PATHS[name] || ICON_PATHS.dot;
  return (
    <svg className={'i' + (cls ? ' ' + cls : '')} viewBox="0 0 24 24" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}
