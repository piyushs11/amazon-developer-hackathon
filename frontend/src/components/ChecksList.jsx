import { useEffect, useRef, useState } from 'react';
import Icon from '../lib/Icon.jsx';

// The list itself. `state` (optional) is a per-check array of 'wait' | 'run' | 'ok' | 'err' | 'warn'
// used while the checks are animating; without it each check shows its own status.
export function ChecksList({ report, state }) {
  return (
    <ul className="checks">
      {report.checks.map((c, i) => {
        const st = state ? state[i] || 'wait' : c.status;
        const ic = st === 'ok' ? <Icon name="check" /> : st === 'err' ? <Icon name="x" /> : st === 'warn' ? <Icon name="alert" /> : null;
        return (
          <li key={c.id} className={st}>
            <span className="ic">{ic}</span>
            <div>
              <div className="t">{c.title}</div>
              {st === 'wait' || st === 'run' ? null : <div className="m">{c.message}</div>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

const stepDelay = () => 380 + Math.random() * 260;

// Static while `run` is 0. Each new `run` above 0 replays the checks one at a time
// (spinner, then result) and calls onDone at the end.
export function CheckRunner({ report, run, onDone }) {
  const [progress, setProgress] = useState({ run: 0, done: 0 });
  const onDoneRef = useRef(onDone);
  const total = report.checks.length;

  useEffect(() => { onDoneRef.current = onDone; });

  useEffect(() => {
    if (!run) return undefined;
    let count = 0;
    let timer;
    const tick = () => {
      count += 1;
      setProgress({ run, done: count });
      if (count < total) timer = setTimeout(tick, stepDelay());
      else if (onDoneRef.current) onDoneRef.current();
    };
    timer = setTimeout(tick, stepDelay());
    return () => clearTimeout(timer);
  }, [run, total]);

  // Progress from an earlier run doesn't count for the current one.
  const done = progress.run === run ? progress.done : 0;
  const state = run ? report.checks.map((c, i) => (i < done ? c.status : i === done ? 'run' : 'wait')) : null;
  return <ChecksList report={report} state={state} />;
}
