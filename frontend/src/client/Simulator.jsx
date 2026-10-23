import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Switch from '../components/Switch.jsx';
import { useToast } from '../components/Toast.jsx';
import Icon from '../lib/Icon.jsx';
import ChatView from '../sim/ChatView.jsx';
import { canSpeak, stopSpeaking, useVoiceInput } from '../sim/speech.js';
import { useClient } from './clientState.jsx';
import { DB } from './mockBackend.js';
import ToolsPanel from './ToolsPanel.jsx';

const TABS = [['ask', 'Ask'], ['tools', 'Tools']];

// The Alexa+ simulator. Ask mode understands requests for any of the user's live services
// (POST /assistant/ask, which calls the gateway); Tools mode is the
// plain MCP client (pick a tool, fill its input_schema, call it).
// opts: { send } asks a question on open, { listen } starts the mic, { mode: 'tools', uuid }.
export default function Simulator({ opts }) {
  const { backend, me, voiceOn, setVoiceOn, closeLayer, chatFor, rememberSim } = useClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [chat] = useState(() => chatFor(me));
  const [mode, setMode] = useState(opts.mode === 'tools' ? 'tools' : 'ask');
  const [text, setText] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [toolsKey, setToolsKey] = useState(0);
  const inputRef = useRef(null);
  const menuRef = useRef(null);
  const moreRef = useRef(null);
  const { listening, listen } = useVoiceInput();

  const startListening = () => listen((t) => { setText(t); inputRef.current?.focus(); });

  useEffect(() => { chat.configure({ voice: voiceOn }); }, [chat, voiceOn]);

  // What the simulator was opened to do.
  useEffect(() => {
    let t;
    if (opts.mode === 'tools') return undefined;
    if (opts.send) t = setTimeout(() => chat.send(opts.send), 250);
    else if (opts.listen) t = setTimeout(startListening, 250);
    else t = setTimeout(() => inputRef.current?.focus(), 100);
    return () => clearTimeout(t);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!menuOpen) return undefined;
    const away = (e) => {
      if (menuRef.current?.contains(e.target) || moreRef.current?.contains(e.target)) return;
      setMenuOpen(false);
    };
    document.addEventListener('click', away);
    return () => document.removeEventListener('click', away);
  }, [menuOpen]);

  const onVoice = (on) => {
    setVoiceOn(on);
    if (!on) stopSpeaking();
    if (on && !canSpeak()) toast("Speech isn't available in this browser.", 'err');
  };
  const clear = () => {
    chat.reset();
    rememberSim(me.id, { results: [] });
    setMenuOpen(false);
    setToolsKey((k) => k + 1);
  };
  const toServices = () => {
    closeLayer();
    navigate(backend.live || backend.link(me.id, DB) ? '/client/services' : `/client/services/${DB}`);
  };
  // Arrow keys, Home and End move between the Ask / Tools tabs.
  const onTabKey = (e) => {
    const i = TABS.findIndex(([id]) => id === mode);
    let next = null;
    if (e.key === 'ArrowRight') next = (i + 1) % TABS.length;
    else if (e.key === 'ArrowLeft') next = (i + TABS.length - 1) % TABS.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = TABS.length - 1;
    if (next === null) return;
    e.preventDefault();
    setMode(TABS[next][0]);
    document.getElementById('sim-tab-' + TABS[next][0])?.focus();
  };
  const submit = (e) => {
    e.preventDefault();
    const v = text;
    setText('');
    chat.send(v);
  };

  return (
    <div className="full">
      <div className="inner">
        <div className="app-top sim-top">
          <button type="button" className="btn-icon btn plain" aria-label="Close" onClick={closeLayer}><Icon name="chevron-down" /></button>
          <div className="title">Alexa+<span className="sub">{me.name}</span></div>
          <button type="button" ref={moreRef} className="btn-icon btn plain" aria-label="Options" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}><Icon name="more" /></button>
          {menuOpen && (
            <div className="kebab-menu" ref={menuRef}>
              <label><span>Read replies aloud</span><Switch on={voiceOn} onChange={onVoice} /></label>
              <button type="button" onClick={clear}>Clear</button>
            </div>
          )}
        </div>
        <div className="sim-tabs" role="tablist" aria-label="Mode" onKeyDown={onTabKey}>
          {TABS.map(([id, label]) => (
            <button
              type="button" role="tab" key={id} id={'sim-tab-' + id}
              aria-selected={mode === id} aria-controls={'sim-panel-' + id} tabIndex={mode === id ? 0 : -1}
              onClick={() => setMode(id)}
            >{label}</button>
          ))}
        </div>
        <div className="sim-panel" role="tabpanel" id="sim-panel-ask" aria-labelledby="sim-tab-ask" hidden={mode !== 'ask'}>
          <ChatView session={chat} onNeedLink={toServices} hidden={mode !== 'ask'} />
          <form className="chat-foot" hidden={mode !== 'ask'} onSubmit={submit}>
            <div className="ask">
              <input ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask Alexa" autoComplete="off" aria-label="Ask Alexa" />
              <button type="button" className={'btn-icon btn plain' + (listening ? ' listening' : '')} aria-label="Speak" onClick={startListening}><Icon name="mic" /></button>
              <button type="submit" className="btn-icon btn send" aria-label="Send" disabled={!text.trim()}><Icon name="send" /></button>
            </div>
          </form>
        </div>
        <div className="tools-panel" role="tabpanel" id="sim-panel-tools" aria-labelledby="sim-tab-tools" hidden={mode !== 'tools'}>
          {mode === 'tools' && <ToolsPanel key={toolsKey} preset={opts.uuid} />}
        </div>
      </div>
    </div>
  );
}
