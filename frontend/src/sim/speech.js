import { useCallback, useState } from 'react';
import { useToast } from '../components/Toast.jsx';

export const canSpeak = () => typeof window !== 'undefined' && !!window.speechSynthesis;

export function speak(text, rate) {
  if (!canSpeak()) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    if (rate) u.rate = rate;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  } catch {
    // Speech is a nice-to-have; ignore browser failures.
  }
}

export function stopSpeaking() {
  if (canSpeak()) window.speechSynthesis.cancel();
}

// Web Speech recognition for the mic buttons. `listen(onResult)` starts one capture.
export function useVoiceInput() {
  const toast = useToast();
  const [listening, setListening] = useState(false);

  const listen = useCallback((onResult) => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { toast("Voice input isn't available in this browser. Type instead.", 'err'); return; }
    try {
      const r = new SR();
      r.lang = 'en-US';
      r.interimResults = false;
      r.maxAlternatives = 1;
      setListening(true);
      r.onresult = (e) => onResult(e.results[0][0].transcript);
      r.onend = () => setListening(false);
      r.onerror = () => { setListening(false); toast("Couldn't hear that. Try again or type.", 'err'); };
      r.start();
    } catch {
      setListening(false);
      toast("Voice input isn't available here. Type instead.", 'err');
    }
  }, [toast]);

  return { listening, listen };
}
