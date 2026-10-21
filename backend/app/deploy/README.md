# deploy

**Owner:** Dev 3

C5 for Dev 2's `publish()`:
```python
from backend.app.deploy import get_deployer, get_registrar

# version = 12-char content hash; bundle_path = bundles/{uuid}/{version}/ (local) or s3://...
result = await get_deployer().deploy(DeployRequest(service_uuid, version, bundle_path))
# GatewayDeployer: every <tool>.py must load -> set_active_version -> mcp_url
# failed load -> status="failed", the old version stays active; same version again -> no-op
reg = await get_registrar().register(name, result.mcp_url, result.version)  # status="mocked"
```
`DEPLOYER=fake` gives a deployer that accepts everything (for pipeline unit tests).
In `MODE=aws`, `s3://` bundle paths are read through Dev 2's `S3Storage`.
