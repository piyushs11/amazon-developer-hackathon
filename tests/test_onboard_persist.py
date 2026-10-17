import ast
import asyncio
import shutil

import pytest

from backend.app.pipeline import flow_onboard as fo
from backend.app.storage.add_n_read_mcp_tool import LocalStorage

UUID = "11111111-1111-1111-1111-111111111111"
SVC = "demo_bistro"

SRC_A = 'async def get_order_status(token, order_id):\n    return "a"\n'
SRC_A_PATCHED = 'async def get_order_status(token, order_id):\n    return "a-fixed"\n'
SRC_B = 'async def place_order(token, item):\n    return "b"\n'
PASS = {"status": "pass", "detail": "verified"}
FAIL = {"status": "fail", "detail": "boom"}


@pytest.fixture
def seeded(cache):
    cache.set_source(SVC, "get_order_status", SRC_A)
    cache.set_endpoint(SVC, "get_order_status", {"tool_name": "get_order_status", "read_only": True})
    cache.set_source(SVC, "place_order", SRC_B)
    cache.set_endpoint(SVC, "place_order", {"tool_name": "place_order", "read_only": False})
    return cache


def test_stores_latest_patched_source_and_consolidated_file(seeded, tmp_path):
    seeded.set_source(SVC, "get_order_status", SRC_A_PATCHED)  # patched after seeding
    storage = LocalStorage(tmp_path)
    out = fo.persist_verified(
        SVC, UUID, {"get_order_status": PASS, "place_order": PASS}, seeded, storage
    )
    files = storage.read_bundle(out["bundle_path"])
    assert set(files) == {"get_order_status.py", "place_order.py", "demo_bistro_tools.py"}
    assert files["get_order_status.py"] == SRC_A_PATCHED
    for name, source in files.items():
        ast.parse(source, filename=name)
    main = files["demo_bistro_tools.py"]
    assert "get_order_statusfordemo_bistro" in main and "placeorder" not in main
    assert "place_orderfordemo_bistro" in main
    assert '"readOnlyHint": True' in main and '"readOnlyHint": False' in main
    assert out["stored"] == ["get_order_status", "place_order"] and out["skipped"] == []


def test_failed_tools_are_not_stored(seeded, tmp_path):
    storage = LocalStorage(tmp_path)
    out = fo.persist_verified(SVC, UUID, {"get_order_status": PASS, "place_order": FAIL}, seeded, storage)
    files = storage.read_bundle(out["bundle_path"])
    assert set(files) == {"get_order_status.py", "demo_bistro_tools.py"}
    assert "place_order" not in files["demo_bistro_tools.py"]
    assert out["skipped"] == ["place_order"]


def test_nothing_verified_writes_nothing(seeded, tmp_path):
    out = fo.persist_verified(SVC, UUID, {"get_order_status": FAIL, "place_order": FAIL}, seeded, LocalStorage(tmp_path))
    assert out == {"bundle_path": None, "version": None, "stored": [], "skipped": ["get_order_status", "place_order"]}
    assert list(tmp_path.iterdir()) == []


def test_same_sources_same_version_changed_source_new_version(seeded, tmp_path):
    storage = LocalStorage(tmp_path)
    results = {"get_order_status": PASS, "place_order": PASS}
    first = fo.persist_verified(SVC, UUID, results, seeded, storage)
    again = fo.persist_verified(SVC, UUID, results, seeded, storage)
    assert again["version"] == first["version"] and again["bundle_path"] == first["bundle_path"]
    seeded.set_source(SVC, "place_order", SRC_B.replace('"b"', '"b2"'))
    changed = fo.persist_verified(SVC, UUID, results, seeded, storage)
    assert changed["version"] != first["version"]
    assert storage.read_bundle(first["bundle_path"])["place_order.py"] == SRC_B  # old version untouched


def test_unparseable_source_is_never_stored(seeded, tmp_path):
    seeded.set_source(SVC, "place_order", "def broken(:\n")
    with pytest.raises(SyntaxError):
        fo.persist_verified(SVC, UUID, {"place_order": PASS}, seeded, LocalStorage(tmp_path))
    assert list(tmp_path.iterdir()) == []


MAPPED = {
    "service_uuid": UUID, "service_name": "Demo Bistro", "base_url": "http://x",
    "endpoints": [
        {"endpoint_id": "get_order_status", "tool_name": "get_order_status", "read_only": True},
        {"endpoint_id": "place_order", "tool_name": "place_order", "read_only": False},
    ],
}


@pytest.mark.parametrize("second,expected", [(PASS, "ok"), (FAIL, "failed")])
def test_onboard_end_to_end(cache, tmp_path, monkeypatch, second, expected):
    def fake_generate(mapped, out_dir):
        assert mapped == MAPPED
        folder = tmp_path / "out" / SVC
        folder.mkdir(parents=True)
        (folder / "get_order_status.py").write_text(SRC_A)
        (folder / "place_order.py").write_text(SRC_B)

    async def fake_verify(service_name, tool_names, **kwargs):
        assert service_name == SVC and tool_names == ["get_order_status", "place_order"]
        return {"get_order_status": PASS, "place_order": second}

    monkeypatch.setattr(fo, "generate", fake_generate)
    monkeypatch.setattr(fo, "verify_service", fake_verify)
    storage = LocalStorage(tmp_path / "store")
    out = asyncio.run(fo.onboard(MAPPED, str(tmp_path / "out"), cache=cache, storage=storage))
    assert out["status"] == expected
    files = storage.read_bundle(out["bundle_path"])
    assert ("place_order.py" in files) == (expected == "ok")
    assert f"/{UUID}/{out['version']}" in out["bundle_path"]


def test_onboard_step_errors(cache, tmp_path, monkeypatch):
    def broken_generate(mapped, out_dir):
        raise RuntimeError("jq missing")

    monkeypatch.setattr(fo, "generate", broken_generate)
    with pytest.raises(fo.OnboardStepError) as e:
        asyncio.run(fo.onboard(MAPPED, str(tmp_path), cache=cache, storage=LocalStorage(tmp_path / "s")))
    assert (e.value.step, e.value.code) == ("codegen", "RuntimeError")

    def ok_generate(mapped, out_dir):
        (tmp_path / "o" / SVC).mkdir(parents=True)
        (tmp_path / "o" / SVC / "get_order_status.py").write_text(SRC_A)
        (tmp_path / "o" / SVC / "place_order.py").write_text(SRC_B)

    async def verify(service_name, tool_names, **kwargs):
        return {"get_order_status": PASS, "place_order": PASS}

    class BrokenStorage:
        def get_latest(self, *a):
            return None

        def exists(self, *a):
            return False

        def write_bundle(self, *a):
            raise OSError("disk full")

    monkeypatch.setattr(fo, "generate", ok_generate)
    monkeypatch.setattr(fo, "verify_service", verify)
    with pytest.raises(fo.OnboardStepError) as e:
        asyncio.run(fo.onboard(MAPPED, str(tmp_path / "o"), cache=cache, storage=BrokenStorage()))
    assert (e.value.step, e.value.code) == ("store", "OSError")


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required by create_folders.sh")
def test_generate_runs_the_real_script_on_stdin(tmp_path):
    mapped = {
        "service_uuid": UUID, "service_name": "Demo Bistro", "base_url": "http://localhost:9000",
        "endpoints": [{
            "endpoint_id": "get_order_status", "tool_name": "get_order_status", "method": "GET",
            "description": "Get the status of an order by its ID.", "path_template": "/orders/{order_id}",
            "read_only": True,
            "params": [{"name": "order_id", "python_type": "str", "json_type": "string",
                        "required": True, "location": "path", "description": "Order ID, e.g. A1042"}],
        }],
    }
    fo.generate(mapped, str(tmp_path))
    folder = tmp_path / "demo_bistro"
    assert sorted(p.name for p in folder.iterdir()) == ["demo_bistro_tools.py", "get_order_status.py"]
    tool = (folder / "get_order_status.py").read_text()
    ast.parse(tool)
    assert "def get_order_statusfordemo_bistro(order_id: str)" in tool and "get_current_token()" in tool
