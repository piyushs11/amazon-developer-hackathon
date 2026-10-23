import { useEffect, useState } from 'react';
import { features as fetchFeatures } from '../lib/api.js';
import { MOCK } from '../lib/config.js';

// What isn't built yet comes from the API (GET /features, backend/app/features.py), loaded once.
// The offline demo (VITE_MOCK=1) has no API, so it shows no badges.
let cache = null;
const listeners = new Set();

function load() {
  if (!cache) {
    cache = (MOCK ? Promise.resolve([]) : fetchFeatures()).catch(() => []);
    cache.then(() => listeners.forEach((fn) => fn()));
  }
  return cache;
}

export function useFeatures() {
  const [list, setList] = useState([]);
  useEffect(() => {
    let live = true;
    load().then((l) => { if (live) setList(l); });
    return () => { live = false; };
  }, []);
  return list;
}

// A small "Not built yet" tag next to a feature that isn't (fully) built; nothing otherwise.
export default function NotBuilt({ id, label }) {
  const feature = useFeatures().find((f) => f.id === id);
  if (!feature || feature.status === 'built') return null;
  const text = label || (feature.status === 'partial' ? 'Partly built' : 'Not built yet');
  return (
    <span className="not-built" title={feature.title + ': ' + feature.detail} tabIndex={0}>
      {text}
    </span>
  );
}
