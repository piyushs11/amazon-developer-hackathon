import { useEffect } from 'react';

// Adds space-separated classes to <body> while the caller is mounted. Each portal scopes its
// page CSS to a body class so overlays rendered into <body> pick up the same styles.
export default function useBodyClass(classes) {
  useEffect(() => {
    const list = (classes || '').split(' ').filter(Boolean);
    if (!list.length) return undefined;
    document.body.classList.add(...list);
    return () => document.body.classList.remove(...list);
  }, [classes]);
}
