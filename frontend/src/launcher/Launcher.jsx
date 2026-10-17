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
            <p>Demo Bistro uploads its connector manifest, passes the automated checks, previews the tools and submits for review.</p>
            <span className="go">Open <Icon name="arrow-right" cls="s" /></span>
          </Link>
          <Link className="role" to="/review">
            <span className="who">Amazon · reviewer</span><h2>Review Console</h2>
            <p>Reads the check report and generated tools, tries them with the test account, then approves or rejects with a reason.</p>
            <span className="go">Open <Icon name="arrow-right" cls="s" /></span>
          </Link>
          <Link className="role" to="/client">
            <span className="who">Client · Alexa+ user</span><h2>Alexa+ app</h2>
            <p>Signs in as Alice or Bob, finds Demo Bistro, connects with OAuth, publishes, then asks in the simulator.</p>
            <span className="go">Open <Icon name="arrow-right" cls="s" /></span>
          </Link>
        </div>
        <div className="flow">
          <h2>Demo order</h2>
          <ol>
            <li>Owner Portal: New submission → use the sample manifest → checks go green → submit.</li>
            <li>Review Console: open Demo Bistro 1.0 → Try it with the test account → Approve.</li>
            <li>Alexa+ app as Alice: search demobistro.test → Connect → sign in → Publish (Generating → Deploying → Registering) → ask "what is the status of order A1042".</li>
            <li>Switch to Bob (More): connect Demo Bistro → Publish finishes instantly → same question at the same MCP URL gives Bob's answer, not Alice's.</li>
            <li>Extras: "Lakeside" shows the pick-one list, pizzapalace.com isn't available, Lakeside Grill's first publish fails and retries, Bob's Lakeside Dental needs a reconnect.</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
