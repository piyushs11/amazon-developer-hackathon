import { createContext, useCallback, useContext, useRef, useState, useSyncExternalStore } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChatSession } from '../sim/chatSession.js';
import { stopSpeaking } from '../sim/speech.js';
import { DB, createMockBackend } from './mockBackend.js';

const ClientContext = createContext(null);
export const useClient = () => useContext(ClientContext);

// Session and UI state for the Alexa+ app. Server data lives in the backend; this re-renders
// whenever the backend reports a change.
export function ClientProvider({ children }) {
  const [backend] = useState(createMockBackend);
  useSyncExternalStore(backend.subscribe, backend.getVersion);
  const navigate = useNavigate();

  const [who, setWho] = useState(null);
  const [query, setQuery] = useState('');
  const [traceOn, setTraceOn] = useState(true);
  const [voiceOn, setVoiceOn] = useState(false);
  // One full-screen layer at a time: the service's sign-in window, the publish screen or the simulator.
  const [layer, setLayer] = useState(null);
  const layerId = useRef(1);
  // Per-user simulator memory (chat session, Tools mode selection and results).
  const sims = useRef({});
  const memoryFor = (userId) => sims.current[userId] || (sims.current[userId] = { uuid: null, tool: null, results: [], chat: null });

  const openLayer = useCallback((type, props) => setLayer({ id: layerId.current++, type, ...props }), []);
  const closeLayer = useCallback(() => { stopSpeaking(); setLayer(null); }, []);

  const value = {
    backend,
    me: who ? backend.user(who) : null,
    signIn: (id) => setWho(id),
    signOut: () => { setLayer(null); setWho(null); },
    query,
    setQuery,
    traceOn,
    setTraceOn,
    voiceOn,
    setVoiceOn,
    layer,
    closeLayer,
    openOAuth: (uuid) => openLayer('oauth', { uuid }),
    openPublish: (uuid) => openLayer('publish', { uuid }),
    openSim: (opts = {}) => openLayer('sim', { opts }),
    // Fix whatever is blocking a connected service: reconnect an expired sign-in, otherwise publish.
    rowAction: (uuid) => {
      const link = backend.link(who, uuid);
      if (link && link.status === 'expired') openLayer('oauth', { uuid });
      else openLayer('publish', { uuid });
    },
    goSearch: () => navigate('/client/services', { state: { focusSearch: Date.now() } }),
    simMemory: memoryFor,
    rememberSim: (userId, patch) => { Object.assign(memoryFor(userId), patch); },
    // Each user keeps one Ask-mode conversation for the whole session.
    chatFor: (user) => {
      const memory = memoryFor(user.id);
      if (!memory.chat) {
        memory.chat = createChatSession({ acct: user.acct, mode: 'client', userId: user.id, intro: 'Hi ' + user.name + '. Ask me anything, or try one of these.', linkButton: true });
        memory.chat.configure({
          // A connected service the user switched off behaves as not connected.
          access: () => {
            const link = backend.link(user.id, DB);
            return link && link.on === false ? 'not_connected' : backend.access(user.id, DB);
          },
          onToolCall: () => backend.touch(user.id, DB),
        });
      }
      return memory.chat;
    },
  };

  return <ClientContext.Provider value={value}>{children}</ClientContext.Provider>;
}
