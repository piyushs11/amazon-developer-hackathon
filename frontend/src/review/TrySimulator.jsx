import { useEffect, useRef, useState } from 'react';
import Switch from '../components/Switch.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import ChatView from '../sim/ChatView.jsx';
import { createChatSession } from '../sim/chatSession.js';
import { canSpeak, stopSpeaking, useVoiceInput } from '../sim/speech.js';
import { useReview } from './reviewState.jsx';

// Alexa+ simulator signed in with the owner's test account. The conversation starts fresh on every
// visit; the test account's orders persist (see ReviewProvider).
export default function TrySimulator({ s }) {
  const { reviewerAcct } = useReview();
  const toast = useToast();
  const [chat] = useState(() => createChatSession({
    acct: reviewerAcct,
    mode: 'review',
    userId: 'reviewer',
    intro: "Hi. I'm signed in to Demo Bistro with the test account. Ask what a customer would ask, like the status of order A1042.",
  }));
  const [showTrace, setShowTrace] = useState(true);
  const [voice, setVoice] = useState(false);
  const [text, setText] = useState('');
  const inputRef = useRef(null);
  const { listening, listen } = useVoiceInput();

  useEffect(() => { chat.configure({ voice }); }, [chat, voice]);
  useEffect(() => stopSpeaking, []);

  const onVoice = (on) => {
    setVoice(on);
    if (!on) stopSpeaking();
    if (on && !canSpeak()) toast("Speech isn't available in this browser.", 'err');
  };
  const submit = (e) => {
    e.preventDefault();
    const v = text;
    setText('');
    chat.send(v);
  };

  return (
    <div className="sim-wrap">
      <div className="sim-head">
        <div className="who"><Icon name="lock" cls="s" /><span>Signed in as</span><b>{s.testAccount.username}</b><span className="tag read">test account</span></div>
        <label className="toggle-row"><span>Show tool calls</span><Switch on={showTrace} onChange={setShowTrace} /></label>
        <label className="toggle-row"><span>Read aloud</span><Switch on={voice} onChange={onVoice} /></label>
      </div>
      <ChatView session={chat} showTrace={showTrace} />
      <form className="sim-foot" onSubmit={submit}>
        <div className="ask">
          <span className="orb"></span>
          <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask as a customer would" autoComplete="off" aria-label="Message" />
          <button type="button" className={'btn-icon btn' + (listening ? ' listening' : '')} aria-label="Speak" onClick={() => listen((t) => { setText(t); inputRef.current.focus(); })}>
            <Icon name="mic" />
          </button>
          <button type="submit" className="btn-icon btn send" aria-label="Send" disabled={!text.trim()}><Icon name="send" /></button>
        </div>
      </form>
    </div>
  );
}
