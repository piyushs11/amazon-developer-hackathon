import asyncio
import json
from pathlib import Path

import pytest

from backend.app.codegen.verifier.utilities import (
    MappedServiceError,
    load_mapped_service,
    service_slug,
)
from backend.app.pipeline import flow_onboard as fo
from backend.app.pipeline.generate_service import generate_service
from backend.app.pipeline.models import GenerationResult
from backend.app.storage.add_n_read_mcp_tool import LocalStorage

UUID = "11111111-1111-1111-1111-111111111111"
SVC = "demo_bistro"
SRC_A = 'async def get_order_status(order_id):\n    return "a"\n'
SRC_B = 'async def place_order(item):\n    return "b"\n'
PASS = {"status": "pass", "detail": "verified"}
FAIL = {"status": "fail", "detail": "Tool: place_order\nError: 404"}

MAPPED = {
    "service_uuid": UUID, "service_name": "Demo Bistro", "base_url": "http://x",
    "endpoints": [
        {"endpoint_id": "get_order_status", "tool_name": "get_order_status", "read_only": True},
        {"endpoint_id": "place_order", "tool_name": "place_order", "read_only": False},
    ],
}


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "bundles", tmp_path / "mapped")


@pytest.fixture
def stubbed(monkeypatch):
    """Replace script + verifier so the pipeline runs without jq, Bedrock or a demo API."""
    state = {"second": PASS}

    def fake_generate(mapped, out_dir):
        folder = Path(out_dir) / SVC
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "get_order_status.py").write_text(SRC_A)
        (folder / "place_order.py").write_text(SRC_B)

    async def fake_verify(service_name, tool_names, **kwargs):
        return {"get_order_status": PASS, "place_order": state["second"]}

    monkeypatch.setattr(fo, "generate", fake_generate)
    monkeypatch.setattr(fo, "verify_service", fake_verify)
    return state


# ---- storage + loader ------------------------------------------------------------------------


def test_mapped_roundtrip_and_name(storage, tmp_path):
    path = storage.write_mapped(UUID, MAPPED)
    assert path == str(tmp_path / "mapped" / f"mapped.{UUID}.json")
    assert storage.read_mapped(UUID) == MAPPED
    assert storage.read_mapped("22222222-2222-2222-2222-222222222222") is None
    with pytest.raises(ValueError):
        storage.read_mapped("../x")


def test_load_mapped_service_valid(storage):
    storage.write_mapped(UUID, MAPPED)
    assert load_mapped_service(UUID, storage) == MAPPED


@pytest.mark.parametrize(
    "data,code",
    [
        (None, "mapped_not_found"),
        ({**MAPPED, "service_uuid": "other"}, "mapped_invalid"),
        ({**MAPPED, "service_name": "!!!"}, "mapped_invalid"),
        ({**MAPPED, "endpoints": []}, "mapped_invalid"),
        ({**MAPPED, "endpoints": [{"tool_name": "Bad-Name"}]}, "mapped_invalid"),
    ],
)
def test_load_mapped_service_errors(storage, data, code):
    if data is not None:
        storage.write_mapped(UUID, data)
    with pytest.raises(MappedServiceError) as e:
        load_mapped_service(UUID, storage)
    assert e.value.code == code


def test_load_mapped_service_invalid_json_and_uuid(storage, tmp_path):
    (tmp_path / "mapped").mkdir()
    (tmp_path / "mapped" / f"mapped.{UUID}.json").write_text("{not json")
    with pytest.raises(MappedServiceError) as e:
        load_mapped_service(UUID, storage)
    assert e.value.code == "mapped_invalid"
    with pytest.raises(MappedServiceError) as e:
        load_mapped_service("../etc", storage)
    assert e.value.code == "invalid_service_uuid"


def test_service_slug_matches_the_script_rule():
    assert service_slug("Demo Bistro") == "demo_bistro"
    assert service_slug("  Joe's  Cafe!! ") == "joe_s_cafe"
    with pytest.raises(ValueError):
        service_slug("123 Diner")  # starts with a digit: not a valid identifier


# ---- generate_service ------------------------------------------------------------------------


def _run(cache, storage, **kw):
    return asyncio.run(generate_service(UUID, cache=cache, storage=storage, **kw))


def test_all_tools_verified_is_ok(cache, storage, stubbed):
    storage.write_mapped(UUID, MAPPED)
    out = _run(cache, storage)
    assert isinstance(out, GenerationResult)
    assert out.status == "ok" and out.errors == []
    assert out.tools == ["get_order_status", "place_order"]
    assert f"/{UUID}/" in out.bundle_path
    files = storage.read_bundle(out.bundle_path)
    assert set(files) == {"get_order_status.py", "place_order.py", "demo_bistro_tools.py"}


def test_failing_tool_gives_failed_with_partial_bundle(cache, storage, stubbed):
    stubbed["second"] = FAIL
    storage.write_mapped(UUID, MAPPED)
    out = _run(cache, storage)
    assert out.status == "failed" and out.tools == ["get_order_status"]
    assert [(e.step, e.code) for e in out.errors] == [("codegen", "tool_not_verified")]
    assert out.errors[0].message.startswith("place_order: ")
    assert set(storage.read_bundle(out.bundle_path)) == {"get_order_status.py", "demo_bistro_tools.py"}


def test_unknown_uuid_fails_at_map_step(cache, storage):
    out = _run(cache, storage)
    assert out.status == "failed" and out.bundle_path is None and out.tools == []
    assert [(e.step, e.code) for e in out.errors] == [("map", "mapped_not_found")]


def test_storage_write_error_is_a_store_step_error(cache, storage, stubbed, monkeypatch):
    storage.write_mapped(UUID, MAPPED)
    monkeypatch.setattr(storage, "write_bundle", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    out = _run(cache, storage)
    assert out.status == "failed"
    assert [(e.step, e.code, e.message) for e in out.errors] == [("store", "OSError", "disk full")]


def test_codegen_error_has_no_stack_trace(cache, storage, monkeypatch):
    storage.write_mapped(UUID, MAPPED)

    def boom(mapped, out_dir):
        raise RuntimeError("jq is required")

    monkeypatch.setattr(fo, "generate", boom)
    out = _run(cache, storage)
    assert [(e.step, e.code, e.message) for e in out.errors] == [("codegen", "RuntimeError", "jq is required")]
    assert "Traceback" not in json.dumps(out.model_dump())


def test_uses_given_out_dir_and_keeps_it(cache, storage, stubbed, tmp_path):
    storage.write_mapped(UUID, MAPPED)
    work = tmp_path / "work"
    work.mkdir()
    assert _run(cache, storage, out_dir=str(work)).status == "ok"
    assert (work / SVC / "get_order_status.py").exists()
