import { useEffect, useRef, useState } from 'react';

// Avatar button with the account popover used in the console headers.
// items: [{ label, onClick }]
export default function AccountMenu({ initials, name, detail, items }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef(null);
  const popRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => {
      if (popRef.current?.contains(e.target) || buttonRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener('click', away);
    return () => document.removeEventListener('click', away);
  }, [open]);

  return (
    <>
      <button
        ref={buttonRef}
        className="avatar"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen((o) => !o)}
      >
        {initials}
      </button>
      {open && (
        <div className="popover" ref={popRef}>
          <div className="who"><b>{name}</b><span>{detail}</span></div>
          {items.map((it) => (
            <button type="button" key={it.label} onClick={() => { setOpen(false); it.onClick(); }}>{it.label}</button>
          ))}
        </div>
      )}
    </>
  );
}
