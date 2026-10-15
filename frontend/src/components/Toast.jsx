import { createContext, useCallback, useContext, useRef, useState } from 'react';
import Icon from '../lib/Icon.jsx';

const ToastContext = createContext(() => {});

// toast(msg, kind?, ms?) where kind is 'ok' | 'err' | undefined, same as the prototype.
export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id) => setItems((list) => list.filter((t) => t.id !== id)), []);

  const toast = useCallback((msg, kind, ms) => {
    const id = nextId.current++;
    setItems((list) => [...list, { id, msg, kind: kind || '', leaving: false }]);
    setTimeout(() => {
      setItems((list) => list.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
      setTimeout(() => dismiss(id), 320);
    }, ms || 4200);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-host">
        {items.map((t) => (
          <div
            key={t.id}
            className={'toast ' + t.kind}
            role="status"
            style={t.leaving ? { transition: 'opacity .3s', opacity: 0 } : undefined}
          >
            <Icon name={t.kind === 'err' ? 'alert' : 'check'} />
            <span>{t.msg}</span>
            <button className="x" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
              <Icon name="x" cls="s" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
