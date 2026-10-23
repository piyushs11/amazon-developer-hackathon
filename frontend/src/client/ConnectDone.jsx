import { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import useBodyClass from '../lib/useBodyClass.js';
import './client.css';

export const OAUTH_CHANNEL = 'mcpb-oauth';

// GET /oauth/callback ends here: /connect/done?status=ok|error. In the sign-in popup this tells
// the app window (OAuthWindow) and closes; in a full tab it goes back to Services.
export default function ConnectDone() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const status = params.get('status') === 'ok' ? 'ok' : 'error';
  useBodyClass('client-page app-bg');

  useEffect(() => {
    try {
      const channel = new BroadcastChannel(OAUTH_CHANNEL);
      channel.postMessage({ status });
      channel.close();
    } catch { /* no BroadcastChannel */ }
    if (window.opener) {
      window.close();
      return;
    }
    navigate('/client/services', { replace: true });
  }, [status, navigate]);

  return (
    <div className="app">
      <div className="app-body">
        <div className="not-avail">
          <h2>{status === 'ok' ? 'Account connected' : "Couldn't connect"}</h2>
          <p className="muted">Returning to MCP Bridge...</p>
        </div>
      </div>
    </div>
  );
}
