# pipeline

**Owner:** Dev 2

`generate_service()` and `publish()` (C6).

## generate_service(service_uuid) -> GenerationResult
Reads `mapped/mapped.{service_uuid}.json`, generates the tool files, verifies each tool,
and stores the verified ones as `bundles/{service_uuid}/{version}/` (version 1, 2, 3...).

## publish(user_id, service_uuid, on_progress) -> PublishResult
```python
from backend.app.pipeline.publish import publish

result = await publish(user_id, service_uuid, on_progress)  # never raises
# first publish:     "generating" -> "deploying" -> "registering" -> "done"
# already published: "skipped" -> "done"            (same mcp_url for every user)
# failure:           ... -> "failed", result.error = StepError(step, code, message)
```
- The user must have connected the service (OAuth) first; otherwise `error.step == "connect"`.
- generate → `Deployer.deploy()` (the bundle must load in the gateway) → `Registrar.register()` (mocked).
- A bundle where some tools failed verification is refused unless `allow_partial=True`.
- A per-service lock means two users publishing at once generate only once.

`PublishResult`: `{status, mcp_url, error, skipped, version}`. This matches what the frontend's
Publish screen expects.
