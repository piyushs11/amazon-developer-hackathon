import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useFeatures } from '../components/NotBuilt.jsx';
import Icon from '../lib/Icon.jsx';
import './launcher.css';

// What isn't built yet, from GET /features (backend/app/features.py).
function ProjectStatus() {
  const pending = useFeatures().filter((f) => f.status !== 'built');
  if (!pending.length) return null;
  return (
    <div className="flow">
      <h2>Not built yet</h2>
      <ol>
        {pending.map((f) => (
          <li key={f.id}>
            <b>{f.title}</b> <span className="not-built">{f.status === 'partial' ? 'Partly built' : 'Not built yet'}</span>
            <div style={{ opacity: 0.8, marginTop: 2 }}>{f.detail}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}

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
        <div className="flow">
          <h2>Demo order</h2>
          <ol>
            <li>Review Console (Jordan Rivera): open Pine &amp; Petal 1.0 → Start review → Try it: search_bouquets with the test account → Approve.</li>
            <li>Alexa+ app as Alice: search pinepetal.test → Connect → Publish (Generating → Deploying → Registering) → ask "show me roses from Pine &amp; Petal", then "send Classic Red Roses to Mom from Pine &amp; Petal" → Yes.</li>
            <li>Switch to Bob (More): connect Pine &amp; Petal → Publish finishes instantly (same MCP URL) → his own account and orders.</li>
            <li>Owner Portal (Priya Shah): New submission → upload the Pine &amp; Petal 1.1 sample (adds order tracking) → checks → submit. Approve it in the Review Console; Alice's next publish generates version 2 with 3 tools.</li>
            <li>Also: "Lakeside" shows the pick-one list, "Lakeside in Evanston" picks one, Bob's Lakeside Dental needs a reconnect, the on/off switch blocks calls, Demo Bistro answers Alice and Bob differently for order A1042.</li>
          </ol>
        </div>
        <ProjectStatus />
      </div>
    </div>
  );
}
