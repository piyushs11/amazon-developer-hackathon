"""publish() regenerates when the approved spec changed since the active bundle was built
(a reviewer approved a new version), and skips when it didn't; the deployer records the hash."""
from backend.app.gateway import bundles
from backend.app.gateway.bundles import InMemoryRegistry
from backend.app.pipeline.publish import publish
from backend.tests.dev3_support import DEMO_UUID
from backend.tests.pipeline.test_publish import FakeGenerate, connected  # noqa: F401


class VersionedRegistry(InMemoryRegistry):
    """An in-memory registry whose spec can change, like Postgres after an approval."""

    def __init__(self):
        super().__init__()
        self.spec = "spec-v1"
        self.recorded: dict[str, str] = {}

    def current_spec_hash(self, service_uuid):
        return self.spec

    def set_active_version(self, service_uuid, version, bundle_path, spec_hash=""):
        super().set_active_version(service_uuid, version, bundle_path, spec_hash)
        self.recorded[service_uuid] = spec_hash

    def spec_changed(self, service_uuid):
        recorded = self.recorded.get(service_uuid)
        return bool(recorded) and recorded != self.spec


def _registry(monkeypatch):
    reg = VersionedRegistry()
    reg.add_service(DEMO_UUID, "http://localhost:9000")
    monkeypatch.setattr(bundles, "_registry", reg)
    return reg


async def test_unchanged_spec_skips_and_changed_spec_regenerates(dev3_env, monkeypatch, connected, tmp_path):  # noqa: F811
    reg = _registry(monkeypatch)
    connected("alice")
    gen = FakeGenerate(tmp_path)

    first = await publish("alice", DEMO_UUID, generate=gen)
    assert first.version == "1" and reg.recorded[DEMO_UUID] == "spec-v1"  # the deployer stored the hash

    again = await publish("alice", DEMO_UUID, generate=gen)
    assert again.skipped is True and gen.calls == 1

    reg.spec = "spec-v2"  # a reviewer approved version 1.1
    stages = []
    updated = await publish("alice", DEMO_UUID, stages.append, generate=gen)
    assert updated.status == "done" and updated.skipped is False and updated.version == "2"
    assert stages == ["generating", "deploying", "registering", "done"]
    assert gen.calls == 2 and reg.get_active_bundle(DEMO_UUID).version == "2"
    assert reg.recorded[DEMO_UUID] == "spec-v2"
