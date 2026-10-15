import { useCallback } from 'react';
import Icon from '../lib/Icon.jsx';
import { useToast } from './Toast.jsx';

export function useCopy() {
  const toast = useToast();
  return useCallback((value) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(
        () => toast('Copied to clipboard', 'ok', 2000),
        () => toast('Select the text to copy it.')
      );
    } else {
      toast('Select the text to copy it.');
    }
  }, [toast]);
}

// Small round copy button. Pass `text` to get a labelled ghost button instead.
export default function CopyButton({ value, label = 'Copy URL', text }) {
  const copy = useCopy();
  if (text) {
    return (
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => copy(value)}>
        <Icon name="copy" cls="s" />{text}
      </button>
    );
  }
  return (
    <button type="button" className="btn-icon btn sm" onClick={() => copy(value)} aria-label={label}>
      <Icon name="copy" cls="s" />
    </button>
  );
}
