"""publish(): generate (fake) -> real GatewayDeployer -> MockRegistrar, on an empty registry."""
import asyncio
import shutil

import pytest

from backend.app.gateway import bundles
from backend.app.gateway.bundles import InMemoryRegistry
from backend.app.pipeline.models import GenerationResult, StepError
from backend.app.pipeline.publish import publish, version_from_path
from backend.tests.dev3_support import DEMO_USER_TOKEN, DEMO_UUID, FIXTURE_BUNDLE, bearer, rpc

URL = f"http://gw.test/mcp/{DEMO_UUID}"


class FakeGenerate:
    """Stands in for generate_service: 'generates' by copying the Demo Bistro bundle."""

    def __init__(self, root, *, result=None, broken=False, delay=0.0):
        self.root, self.result, self.broken, self.delay = root, result, broken, delay
        self.calls = 0

    async def __call__(self, service_uuid):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.result is not None:
            return self.result
        dest = self.root / "bundles" / service_uuid / str(self.calls)
        shutil.copytree(FIXTURE_BUNDLE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.md"))
        if self.broken:
            (dest / "search_menu.py").write_text("this is not python")
        return GenerationResult(service_uuid=service_uuid, status="ok", bundle_path=str(dest),
                                tools=["get_order_status", "place_order", "search_menu"])


@pytest.fixture
def registry(dev3_env, monkeypatch):
    """A registry where Demo Bistro exists but has never been published."""
    reg = InMemoryRegistry()
    reg.add_service(DEMO_UUID, "http://localhost:9000")
    monkeypatch.setattr(bundles, "_registry", reg)
    return reg


@pytest.fixture
def connected():
    from backend.app.auth.factory import get_mapping

    def connect(user_id):
        get_mapping().upsert_connection(user_id, DEMO_UUID, "active")
    return connect


async def test_first_publish_generates_deploys_registers(registry, connected, tmp_path, client):
    connected("alice")
    gen, stages = FakeGenerate(tmp_path), []
    result = await publish("alice", DEMO_UUID, stages.append, generate=gen)

    assert result.status == "done", result
    assert result.mcp_url == URL and result.version == "1" and result.skipped is False
    assert stages == ["generating", "deploying", "registering", "done"]
    assert gen.calls == 1
    assert registry.get_active_bundle(DEMO_UUID).version == "1"

    # The published bundle is what the gateway now serves.
    resp = await client.post(f"/mcp/{DEMO_UUID}", headers=bearer(DEMO_USER_TOKEN),
                             json=rpc("tools/list"))
    assert len(resp.json()["result"]["tools"]) == 3


async def test_second_user_skips_generation(registry, connected, tmp_path):
    connected("alice")
    connected("bob")
    gen = FakeGenerate(tmp_path)
    await publish("alice", DEMO_UUID, generate=gen)
    stages = []
    result = await publish("bob", DEMO_UUID, stages.append, generate=gen)

    assert result.status == "done" and result.skipped is True
    assert result.mcp_url == URL and result.version == "1"
    assert stages == ["skipped", "done"]
    assert gen.calls == 1


async def test_not_connected_user_is_refused_before_generating(registry, tmp_path):
    gen, stages = FakeGenerate(tmp_path), []
    result = await publish("carol", DEMO_UUID, stages.append, generate=gen)
    assert result.status == "failed" and result.error.step == "connect"
    assert stages == ["failed"] and gen.calls == 0


async def test_generation_failure_is_reported(registry, connected, tmp_path):
    connected("alice")
    failed = GenerationResult(service_uuid=DEMO_UUID, status="failed", errors=[
        StepError(step="map", code="mapped_not_found", message="no mapped service stored")])
    stages = []
    result = await publish("alice", DEMO_UUID, stages.append,
                           generate=FakeGenerate(tmp_path, result=failed))
    assert result.status == "failed"
    assert (result.error.step, result.error.code) == ("map", "mapped_not_found")
    assert stages == ["generating", "failed"]
    assert registry.get_active_bundle(DEMO_UUID) is None


async def test_partly_verified_bundle_refused_unless_allowed(registry, connected, tmp_path):
    connected("alice")
    dest = tmp_path / "bundles" / DEMO_UUID / "1"
    shutil.copytree(FIXTURE_BUNDLE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.md"))
    partial = GenerationResult(
        service_uuid=DEMO_UUID, status="failed", bundle_path=str(dest), tools=["search_menu"],
        errors=[StepError(step="codegen", code="tool_not_verified", message="place_order: 500")])

    refused = await publish("alice", DEMO_UUID, generate=FakeGenerate(tmp_path, result=partial))
    assert refused.status == "failed" and refused.error.code == "tool_not_verified"

    allowed = await publish("alice", DEMO_UUID, generate=FakeGenerate(tmp_path, result=partial),
                            allow_partial=True)
    assert allowed.status == "done" and allowed.version == "1"


async def test_bundle_that_does_not_load_fails_at_deploy(registry, connected, tmp_path):
    connected("alice")
    stages = []
    result = await publish("alice", DEMO_UUID, stages.append,
                           generate=FakeGenerate(tmp_path, broken=True))
    assert result.status == "failed" and result.error.step == "deploy"
    assert stages == ["generating", "deploying", "failed"]
    assert registry.get_active_bundle(DEMO_UUID) is None


async def test_failed_registration_is_reported(registry, connected, tmp_path):
    from contracts.models import RegisterResult

    class BrokenRegistrar:
        async def register(self, name, mcp_url, version):
            return RegisterResult(addon_id="", status="failed")

    connected("alice")
    result = await publish("alice", DEMO_UUID, generate=FakeGenerate(tmp_path),
                           registrar=BrokenRegistrar())
    assert result.status == "failed" and result.error.step == "register"


async def test_concurrent_publishes_generate_once(registry, connected, tmp_path):
    connected("alice")
    connected("bob")
    gen = FakeGenerate(tmp_path, delay=0.05)
    a, b = await asyncio.gather(publish("alice", DEMO_UUID, generate=gen),
                                publish("bob", DEMO_UUID, generate=gen))
    assert gen.calls == 1
    assert {a.skipped, b.skipped} == {False, True}
    assert a.mcp_url == b.mcp_url == URL


async def test_progress_callback_errors_do_not_stop_publish(registry, connected, tmp_path):
    connected("alice")

    def broken(stage):
        raise RuntimeError("ui went away")

    result = await publish("alice", DEMO_UUID, broken, generate=FakeGenerate(tmp_path))
    assert result.status == "done"


def test_version_from_path():
    assert version_from_path("generated/bundles/u/3") == "3"
    assert version_from_path("C:\\x\\bundles\\u\\12\\") == "12"
    assert version_from_path("s3://bucket/bundles/u/7/") == "7"
