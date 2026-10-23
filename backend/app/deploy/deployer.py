"""C5: publish a bundle version to the gateway, and register it with Alexa+ (mocked).

publish() (Dev 2) calls deploy(DeployRequest(service_uuid, version, bundle_path)) where
version is the 12-char content hash and bundle_path is bundles/{uuid}/{version}/ locally
or an s3:// path in MODE=aws.

GatewayDeployer.deploy():
  1. every tool file of the bundle must load (runtime/loader.py)
  2. only then mark it active in the registry -> next MCP call uses it, no restart
If step 1 fails, the previously active version stays active.
"""
import asyncio
import hashlib
import logging

from backend.app.auth.settings import get_settings
from backend.app.gateway.bundles import get_registry
from contracts.models import DeployRequest, DeployResult, RegisterResult
from runtime import loader

log = logging.getLogger("mcp_bridge.deploy")


def mcp_url(service_uuid: str) -> str:
    return f"{get_settings().gateway_url}/mcp/{service_uuid}"


class GatewayDeployer:
    async def deploy(self, req: DeployRequest) -> DeployResult:
        url = mcp_url(req.service_uuid)
        registry = get_registry()
        try:
            bundle = await asyncio.to_thread(
                loader.load, req.service_uuid, req.version, req.bundle_path
            )
        except loader.BundleLoadError as exc:
            log.warning("deploy_rejected service_uuid=%s version=%s error=%s",
                        req.service_uuid, req.version, exc)
            return DeployResult(mcp_url=url, version=req.version, status="failed", error=str(exc))

        current = await asyncio.to_thread(registry.get_active_bundle, req.service_uuid)
        if current and current.version == req.version and current.bundle_path == req.bundle_path:
            return DeployResult(mcp_url=url, version=req.version, status="deployed")  # idempotent

        # Record which spec this bundle was built from, so publish() can tell when it's stale.
        spec_hash_of = getattr(registry, "current_spec_hash", None)
        spec_hash = await asyncio.to_thread(spec_hash_of, req.service_uuid) if spec_hash_of else ""
        try:
            await asyncio.to_thread(
                registry.set_active_version,
                req.service_uuid, req.version, req.bundle_path, spec_hash,
            )
        except LookupError as exc:
            return DeployResult(mcp_url=url, version=req.version, status="failed", error=str(exc))
        log.info("deployed service_uuid=%s version=%s tools=%d",
                 req.service_uuid, req.version, len(bundle.tools))
        return DeployResult(mcp_url=url, version=req.version, status="deployed")


class FakeDeployer:
    """For Dev 2's pipeline tests: accepts everything, touches nothing."""

    async def deploy(self, req: DeployRequest) -> DeployResult:
        return DeployResult(mcp_url=mcp_url(req.service_uuid), version=req.version,
                            status="deployed")


class MockRegistrar:
    """Alexa+ MCP Toolkit access is partner-only: pretend to register."""

    async def register(self, name: str, mcp_url: str, version: str) -> RegisterResult:
        addon_id = "mock-" + hashlib.sha256(mcp_url.encode()).hexdigest()[:12]
        log.info("register_mocked name=%s mcp_url=%s version=%s", name, mcp_url, version)
        return RegisterResult(addon_id=addon_id, status="mocked")
