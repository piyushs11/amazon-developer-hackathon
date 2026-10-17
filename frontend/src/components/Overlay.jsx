import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const OverlayContext = createContext(null);

// open(node, { sheet, sticky }) shows one modal (or a bottom sheet) at a time; opening another
// replaces it. Escape and a backdrop click close it unless `sticky`.
export function useOverlay() {
  return useContext(OverlayContext);
}

export function OverlayProvider({ children }) {
  const [current, setCurrent] = useState(null);
  const nextId = useRef(1);

  const open = useCallback((node, opts = {}) => setCurrent({ id: nextId.current++, node, ...opts }), []);
  const close = useCallback(() => setCurrent(null), []);

  useEffect(() => {
    if (!current) return undefined;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => { if (e.key === 'Escape') setCurrent(null); };
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
    };
  }, [current]);

  const api = useMemo(() => ({ open, close }), [open, close]);

  return (
    <OverlayContext.Provider value={api}>
      {children}
      {current && createPortal(<Backdrop key={current.id} overlay={current} onClose={close} />, document.body)}
    </OverlayContext.Provider>
  );
}

function Backdrop({ overlay, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const t = setTimeout(() => {
      const first = ref.current && ref.current.querySelector('input,textarea,button.btn-primary,button');
      if (first) first.focus();
    }, 30);
    return () => clearTimeout(t);
  }, []);

  const onClick = (e) => { if (e.target === e.currentTarget && !overlay.sticky) onClose(); };

  return (
    <div className={'backdrop' + (overlay.sheet ? ' sheet' : '')} ref={ref} onClick={onClick}>
      {overlay.sheet ? (
        <div className="sheet-panel" role="dialog" aria-modal="true"><div className="grab"></div>{overlay.node}</div>
      ) : (
        <div className="modal" role="dialog" aria-modal="true">{overlay.node}</div>
      )}
    </div>
  );
}
