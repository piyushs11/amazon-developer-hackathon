// On/off toggle styled by .switch in the design system.
export default function Switch({ on, onChange, label, style }) {
  return (
    <button
      type="button"
      className="switch"
      role="switch"
      aria-checked={!!on}
      aria-label={label}
      style={style}
      onClick={() => onChange(!on)}
    />
  );
}
