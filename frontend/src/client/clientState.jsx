import { createContext, useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useNavigate } from 'react-router-dom';
import { MOCK } from '../lib/config.js';
import { createChatSession } from '../sim/chatSession.js';
import { createRealChatSession } from '../sim/realChatSession.js';
import { stopSpeaking } from '../sim/speech.js';
import { DB, createMockBackend } from './mockBackend.js';
import { createRealBackend } from './realBackend.js';

// The signed-in user survives a reload (and the full-page OAuth redirect when popups are blocked).
// Only the username is kept: demo-login needs no password, so a fresh token is fetched on load.
const SESSION_KEY = 'mcpb.user';
const savedUser = () => { try { return MOCK ? null : sessionStorage.getItem(SESSION_KEY); } catch { return null; } };
const saveUser = (id) => {
  try { if (id) sessionStorage.setItem(SESSION_KEY, id); else sessionStorage.removeItem(SESSION_KEY); } catch { /* storage blocked */ }
};

const ClientContext = createContext(null);
export const useClient = () => useContext(ClientContext);

// Session and UI state for the Alexa+ app. Server data lives in the backend; this re-renders
// whenever the backend reports a change.
export function ClientProvider({ children }) {
  const [backend] = useState(() => (MOCK ? createMockBackend() : createRealBackend()));
  useSyncExternalStore(backend.subscribe, backend.getVersion);
  const navigate = useNavigate();

  const [who, setWho] = useState(null);
  const [restoring, setRestoring] = useState(() => !!savedUser());
  const [query, setQuery] = useState('');
  const [voiceOn, setVoiceOn] = useState(false);
  // One full-screen layer at a time: the service's sign-in window, the publish screen or the simulator.
  const [layer, setLayer] = useState(null);
  const layerId = useRef(1);
  // Per-user simulator memory (chat session, Tools mode selection and results).
  const sims = useRef({});
  const memoryFor = (userId) => sims.current[userId] || (sims.current[userId] = { uuid: null, tool: null, results: [], chat: null });

  // Real API: the demo accounts for the sign-in screen, and a saved session to restore.
  const [loadError, setLoadError] = useState(null);
  useEffect(() => {
    if (backend.init) backend.init().catch((e) => setLoadError(e.message));
    const id = savedUser();
    if (!id) return;
    backend.login(id)
      .then((u) => setWho(u.id))
      .catch(() => saveUser(null))
      .finally(() => setRestoring(false));
  }, [backend]);
  // The catalog feeds the "Try" chips and suggestions; load it once someone is signed in.
  useEffect(() => {
    if (who && backend.loadCatalog) backend.loadCatalog().catch(() => {});
  }, [backend, who]);

  const openLayer = useCallback((type, props) => setLayer({ id: layerId.current++, type, ...props }), []);
  const closeLayer = useCallback(() => { stopSpeaking(); setLayer(null); }, []);

  const value = {
    backend,
    me: who ? backend.user(who) : null,
    restoring,
    loadError,
    // `id` must already be signed in with backend.login (that is what fetches the user token).
    signIn: (id) => { saveUser(id); setWho(id); },
    signOut: () => { setLayer(null); saveUser(null); setWho(null); },
    query,
    setQuery,
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
        const intro = 'Hi ' + user.name + '. Ask me anything, or try one of these.';
        if (MOCK) {
          memory.chat = createChatSession({ acct: user.acct, mode: 'client', userId: user.id, intro, linkButton: true });
          memory.chat.configure({
            // A connected service the user switched off behaves as not connected.
            access: () => {
              const link = backend.link(user.id, DB);
              return link && link.on === false ? 'not_connected' : backend.access(user.id, DB);
            },
            onToolCall: () => backend.touch(user.id, DB),
          });
        } else {
          // Starter chips: one example phrase from each of the user's live services.
          const starters = () => backend.myServices(user.id)
            .filter((s) => s.status === 'active' && s.on)
            .flatMap((s) => (s.phrases || []).slice(0, 2)).slice(0, 4);
          memory.chat = createRealChatSession({
            userId: user.id, intro, linkButton: true, starters,
            ask: (text, pending, mem) => backend.ask(user.id, text, pending, mem),
          });
        }
      }
      return memory.chat;
    },
  };

  return <ClientContext.Provider value={value}>{children}</ClientContext.Provider>;
}
