"""publish(user_id, service_uuid, on_progress): make a service's tools live (contract C6).

    first publish of a service:
        "generating"  -> generate_service(uuid)        writes bundles/{uuid}/{version}/ (1, 2, 3...)
        "deploying"   -> Deployer.deploy(...)          bundle must load, then becomes active
        "registering" -> Registrar.register(...)       Alexa+ (mocked)
    already published by another user:
        "skipped"                                      same bundle, same mcp_url for everyone
    then always:
        "done" -> PublishResult(status="done", mcp_url="{GATEWAY_URL}/mcp/{uuid}")
    any failure:
        "failed" -> PublishResult(status="failed", error=StepError(step=..., code=..., message=...))

The user must have connected the service (OAuth) first; generation never depends on the user.
A per-service lock stops two users publishing the same service at once from both generating.
Never raises.
"""
import asyncio
import inspect
import logging
from collections.abc import Callable
from pathlib import PurePosixPath

from backend.app.pipeline.models import PublishResult, StepError
from contracts.models import DeployRequest

log = logging.getLogger("mcp_bridge.publish")
MAX_MESSAGE = 300

# One lock per service. Fine for one gateway process; several instances would need a DB lock.
_locks: dict[str, asyncio.Lock] = {}


def _lock(service_uuid: str) -> asyncio.Lock:
    return _locks.setdefault(service_uuid, asyncio.Lock())


def version_from_path(bundle_path: str) -> str:
    """bundles/{uuid}/{version}/ (local or s3://...) -> version."""
    return PurePosixPath(bundle_path.replace("\\", "/").rstrip("/")).name


async def publish(
    user_id: str, service_uuid: str, on_progress: Callable[[str], object] | None = None, *,
    generate=None, deployer=None, registrar=None, registry=None, mapping=None,
    allow_partial: bool = False,
) -> PublishResult:
    """Publish `service_uuid` for `user_id`. The keyword arguments replace the defaults in tests.

    allow_partial=False: a bundle where some tools failed verification is not published.
    """
    from backend.app.auth.factory import get_mapping
    from backend.app.deploy import get_deployer, get_registrar, mcp_url
    from backend.app.gateway.bundles import get_registry

    mapping = mapping or get_mapping()
    registry = registry or get_registry()
    url = mcp_url(service_uuid)

    async def progress(stage: str) -> None:
        if on_progress is None:
            return
        try:
            out = on_progress(stage)
            if inspect.isawaitable(out):
                await out
        except Exception:  # noqa: BLE001 — a broken progress callback must not stop publishing
            log.warning("on_progress failed at stage=%s", stage)

    async def fail(step: str, code: str, message: str) -> PublishResult:
        log.warning("publish_failed service_uuid=%s user_id=%s step=%s code=%s",
                    service_uuid, user_id, step, code)
        await progress("failed")
        return PublishResult(status="failed",
                             error=StepError(step=step, code=code, message=message[:MAX_MESSAGE]))

    # The user must have connected the service before it is published for them.
    try:
        connection = await asyncio.to_thread(mapping.get_connection, user_id, service_uuid)
    except Exception as exc:  # noqa: BLE001
        return await fail("connect", type(exc).__name__, "could not check the connection")
    if connection is None or connection.status != "active":
        return await fail("connect", "NOT_CONNECTED",
                          "Connect the service in MCP Bridge before publishing it.")

    async with _lock(service_uuid):
        active = await asyncio.to_thread(registry.get_active_bundle, service_uuid)
        if active is not None:
            await progress("skipped")
            await progress("done")
            return PublishResult(status="done", mcp_url=url, skipped=True, version=active.version)

        # 1. generate (Dev 2): files written to storage as the next version
        await progress("generating")
        if generate is None:
            from backend.app.pipeline.generate_service import generate_service as generate
        try:
            gen = await generate(service_uuid)
        except Exception as exc:  # noqa: BLE001 — generate_service should never raise, but be safe
            return await fail("codegen", type(exc).__name__, str(exc))
        if gen.status != "ok" and not (allow_partial and gen.bundle_path):
            first = gen.errors[0] if gen.errors else None
            if first is not None:
                return await fail(first.step, first.code, first.message)
            return await fail("codegen", "GENERATION_FAILED", "generation failed")
        if not gen.bundle_path:
            return await fail("store", "NO_BUNDLE", "generation returned no bundle")
        version = version_from_path(gen.bundle_path)

        # 2. deploy (Dev 3): the bundle must load, then it becomes the active version
        await progress("deploying")
        deployer = deployer or get_deployer()
        try:
            deployed = await deployer.deploy(DeployRequest(
                service_uuid=service_uuid, version=version, bundle_path=gen.bundle_path))
        except Exception as exc:  # noqa: BLE001
            return await fail("deploy", type(exc).__name__, str(exc))
        if deployed.status != "deployed":
            return await fail("deploy", "BUNDLE_LOAD_FAILED",
                              deployed.error or "the bundle did not load in the gateway")

        # 3. register (Dev 3): mocked Alexa+ registration
        await progress("registering")
        registrar = registrar or get_registrar()
        name = await asyncio.to_thread(_service_name, service_uuid)
        try:
            registered = await registrar.register(name, deployed.mcp_url, version)
        except Exception as exc:  # noqa: BLE001
            return await fail("register", type(exc).__name__, str(exc))
        if registered.status == "failed":
            return await fail("register", "REGISTER_FAILED", "Alexa+ registration failed")

    log.info("published service_uuid=%s version=%s by user_id=%s", service_uuid, version, user_id)
    await progress("done")
    return PublishResult(status="done", mcp_url=deployed.mcp_url, version=version)


def _service_name(service_uuid: str) -> str:
    from backend.app.auth.factory import get_service_directory

    try:
        info = get_service_directory().get(service_uuid)
    except Exception:  # noqa: BLE001
        info = None
    return info.service_name if info else service_uuid
