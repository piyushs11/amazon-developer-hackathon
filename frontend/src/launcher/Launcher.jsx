import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import Icon from '../lib/Icon.jsx';
import './launcher.css';

export default function Launcher() {
  useEffect(() => {
    document.title = 'MCP Bridge Prototype';
    document.body.classList.add('launcher-page');
    return () => document.body.classList.remove('launcher-page');
  }, []);

  return (
    <div className="launcher">
      <div className="wrap">
        <div className="hero">
          <span className="mark"><Icon name="bridge" /></span>
          <h1>MCP Bridge</h1>
        </div>
        <p className="lede">
          Universal Alexa+ connector. A website owner describes its API in one manifest and Amazon approves it.
          A user connects their account and publishes it; the tools are generated once per service and served by
          one MCP gateway at <code>/mcp/{'{service_uuid}'}</code>. The URL picks the service, the user token picks the account.
        </p>
        <div className="roles">
          <Link className="role" to="/owner">
            <span className="who">Owner · third-party website</span><h2>Owner Portal</h2>
            <p>A business uploads its API as a connector manifest, passes the automated checks, previews the MCP tools and submits for review.</p>
            <span className="go">Open <Icon name="arrow-right" cls="s" /></span>
          </Link>
          <Link className="role" to="/review">
            <span className="who">Amazon · reviewer</span><h2>Review Console</h2>
            <p>Reads the check report and tools, tries them against the real API with the test account, then approves (into the catalog) or rejects with a reason.</p>
            <span className="go">Open <Icon name="arrow-right" cls="s" /></span>
          </Link>
          <Link className="role" to="/client">
            <span className="who">Client · Alexa+ user</span><h2>Alexa+ app</h2>
            <p>Finds a service, connects with OAuth, publishes it (the MCP server is generated), then asks in the simulator.</p>
            <span className="go">Open <Icon name="arrow-right" cls="s" /></span>
          </Link>
        </div>
      </div>
    </div>
  );
}
