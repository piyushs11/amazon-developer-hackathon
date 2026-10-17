# deploy

**Owner:** Dev 3

C5 for Dev 2's `publish()`:
```python
from backend.app.deploy import get_deployer, get_registrar

result = await get_deployer().deploy(DeployRequest(service_uuid, version, bundle_path))
# GatewayDeployer: bundle must load (TOOLS) -> set_active_version -> mcp_url
# failed load -> status="failed", the old version stays active; same version again -> no-op
reg = await get_registrar().register(name, result.mcp_url, result.version)  # status="mocked"
```
`DEPLOYER=fake` gives a deployer that accepts everything (for pipeline unit tests).
If the bundle manifest has a `spec_hash`, it is stored with the active version.
