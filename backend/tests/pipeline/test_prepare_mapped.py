"""The map step of publish(): registry -> mapped JSON in storage -> readable by generate_service."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.codegen.verifier.utilities import load_mapped_service
from backend.app.db import registry
from backend.app.gateway import bundles
from backend.app.gateway.bundles import InMemoryRegistry
from backend.app.mapper import map_service
from backend.app.pipeline.models import GenerationResult
from backend.app.pipeline.prepare_mapped import PrepareError, prepare_mapped
from backend.app.pipeline.publish import publish
from backend.app.spec import parse_spec
from backend.app.storage.add_n_read_mcp_tool import LocalStorage
from backend.tests.dev3_support import DEMO_UUID, ROOT

FIXTURE = json.loads((ROOT / "contracts/fixtures/mapped.demo_bistro.json").read_text())


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "bundles", tmp_path / "mapped")


@pytest.fixture
def pg_registry(dev3_env, monkeypatch):
    """REGISTRY=postgres with the registry functions replaced by what seed.py would have stored."""
    dev3_env(REGISTRY="postgres")
    raw = json.loads((ROOT / "mock-services/catalog/specs/demo_bistro.json").read_text())
    spec = parse_spec(raw)
    mapped = map_service(spec)
    row = SimpleNamespace(service_uuid=spec.service_uuid, service_name=spec.service_name)
    state = {"rows": {spec.service_uuid: (row, mapped.endpoints)}}

    monkeypatch.setattr(registry, "get_service", lambda uuid: state["rows"].get(uuid, (None,))[0])
    monkeypatch.setattr(registry, "get_endpoints", lambda uuid: state["rows"][uuid][1])
    state["ensured"] = []
    monkeypatch.setattr(registry, "ensure_business", lambda uuid: state["ensured"].append(uuid) or True)
    return state


# ---- prepare_mapped ----

def test_builds_mapped_json_from_the_registry(pg_registry, storage):
    path = prepare_mapped(DEMO_UUID, storage=storage)
    assert Path(path).name == f"mapped.{DEMO_UUID}.json"
    assert storage.read_mapped(DEMO_UUID) == FIXTURE  # same as map_service(parse_spec(spec))


def test_ensures_the_business_row_for_the_service(pg_registry, storage):
    prepare_mapped(DEMO_UUID, storage=storage)
    assert pg_registry["ensured"] == [DEMO_UUID]


def test_business_trouble_never_blocks_the_map_step(pg_registry, storage, monkeypatch):
    def boom(uuid):
        raise RuntimeError("db down")

    monkeypatch.setattr(registry, "ensure_business", boom)
    assert Path(prepare_mapped(DEMO_UUID, storage=storage)).exists()


def test_output_is_what_generate_service_accepts(pg_registry, storage):
    prepare_mapped(DEMO_UUID, storage=storage)
    mapped = load_mapped_service(DEMO_UUID, storage)  # generate_service's own validation
    assert [e["tool_name"] for e in mapped["endpoints"]] == [
        "search_menu", "get_order_status", "place_order"]


def test_rerun_refreshes_the_stored_json(pg_registry, storage):
    prepare_mapped(DEMO_UUID, storage=storage)
    row, endpoints = pg_registry["rows"][DEMO_UUID]
    pg_registry["rows"][DEMO_UUID] = (row, endpoints[:1])  # spec changed: one endpoint left
    prepare_mapped(DEMO_UUID, storage=storage)
    assert len(storage.read_mapped(DEMO_UUID)["endpoints"]) == 1


def test_unknown_service_and_no_endpoints(pg_registry, storage):
    with pytest.raises(PrepareError) as e:
        prepare_mapped("22222222-2222-2222-2222-222222222222", storage=storage)
    assert (e.value.step, e.value.code) == ("map", "SERVICE_NOT_FOUND")

    row, _ = pg_registry["rows"][DEMO_UUID]
    pg_registry["rows"][DEMO_UUID] = (row, [])
    with pytest.raises(PrepareError) as e:
        prepare_mapped(DEMO_UUID, storage=storage)
    assert (e.value.step, e.value.code) == ("map", "NO_ENDPOINTS")
    assert storage.read_mapped(DEMO_UUID) is None  # nothing half-written


def test_registry_down_is_a_map_error(pg_registry, storage, monkeypatch):
    def boom(uuid):
        raise ConnectionError("postgres is down: password=secret")

    monkeypatch.setattr(registry, "get_service", boom)
    with pytest.raises(PrepareError) as e:
        prepare_mapped(DEMO_UUID, storage=storage)
    assert (e.value.step, e.value.code) == ("map", "REGISTRY_ERROR")
    assert "secret" not in e.value.message


def test_storage_failure_is_a_store_error(pg_registry):
    class BrokenStorage:
        def write_mapped(self, service_uuid, data):
            raise OSError("disk full")

    with pytest.raises(PrepareError) as e:
        prepare_mapped(DEMO_UUID, storage=BrokenStorage())
    assert (e.value.step, e.value.code) == ("store", "OSError")


def test_memory_registry_uses_the_fixture(dev3_env, storage):
    prepare_mapped(DEMO_UUID, storage=storage)  # REGISTRY=memory
    assert storage.read_mapped(DEMO_UUID) == FIXTURE
    with pytest.raises(PrepareError) as e:
        prepare_mapped("22222222-2222-2222-2222-222222222222", storage=storage)
    assert e.value.code == "SERVICE_NOT_FOUND"


# ---- inside publish() ----

@pytest.fixture
def empty_registry(dev3_env, monkeypatch):
    reg = InMemoryRegistry()
    reg.add_service(DEMO_UUID, "http://localhost:9000")
    monkeypatch.setattr(bundles, "_registry", reg)
    return reg


@pytest.fixture
def connected(empty_registry):
    from backend.app.auth.factory import get_mapping

    get_mapping().upsert_connection("alice", DEMO_UUID, "active")


async def test_publish_maps_before_generating(empty_registry, connected):
    order = []

    def prepare(service_uuid):
        order.append("map")

    async def generate(service_uuid):
        order.append("generate")
        return GenerationResult(service_uuid=service_uuid, status="failed")

    stages = []
    await publish("alice", DEMO_UUID, stages.append, generate=generate, prepare=prepare)
    assert order == ["map", "generate"]
    assert stages[0] == "generating"  # the map step runs inside the "generating" stage


async def test_map_failure_is_reported_and_generation_never_runs(empty_registry, connected):
    def prepare(service_uuid):
        raise PrepareError("map", "SERVICE_NOT_FOUND", "service is not in the registry")

    calls = []

    async def generate(service_uuid):
        calls.append(service_uuid)

    stages = []
    result = await publish("alice", DEMO_UUID, stages.append, generate=generate, prepare=prepare)
    assert result.status == "failed"
    assert (result.error.step, result.error.code) == ("map", "SERVICE_NOT_FOUND")
    assert stages == ["generating", "failed"] and calls == []


async def test_unexpected_map_error_is_a_map_step_error(empty_registry, connected):
    def prepare(service_uuid):
        raise ValueError("bad row")

    result = await publish("alice", DEMO_UUID, generate=lambda u: None, prepare=prepare)
    assert (result.error.step, result.error.code) == ("map", "ValueError")


async def test_default_prepare_runs_with_the_real_generator(empty_registry, connected, monkeypatch):
    """No fakes injected: publish() calls prepare_mapped, then generate_service."""
    seen = []
    monkeypatch.setattr("backend.app.pipeline.prepare_mapped.prepare_mapped",
                        lambda uuid: seen.append(("map", uuid)))

    async def fake_generate_service(uuid, **kw):
        seen.append(("generate", uuid))
        return GenerationResult(service_uuid=uuid, status="failed")

    monkeypatch.setattr("backend.app.pipeline.generate_service.generate_service",
                        fake_generate_service)
    await publish("alice", DEMO_UUID)
    assert seen == [("map", DEMO_UUID), ("generate", DEMO_UUID)]


async def test_already_published_service_is_not_mapped_again(empty_registry, connected):
    empty_registry.set_active_version(DEMO_UUID, "1", "somewhere")
    calls = []
    result = await publish("alice", DEMO_UUID, prepare=lambda u: calls.append(u))
    assert result.skipped is True and calls == []
