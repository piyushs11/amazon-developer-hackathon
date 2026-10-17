import asyncio

import pytest

from backend.app.codegen.verifier import hit_endpoint as he
from backend.app.storage.add_n_read_mcp_tool import LocalStorage
from backend.app.storage.error_files import (
    LocalErrorStorage,
    S3ErrorStorage,
    get_error_storage,
)
from tests.test_dev_token_verifier import FAIL_SRC, OK_SRC, StubBedrock
from tests.test_storage import FakeS3

UUID = "11111111-1111-1111-1111-111111111111"


def test_local_same_layout_as_bundles_and_overwrite(tmp_path):
    bundles, errors = LocalStorage(tmp_path / "bundles"), LocalErrorStorage(tmp_path / "errors")
    bundle = bundles.write_bundle(UUID, "2", {"get_thing.py": "ok\n"})
    path = errors.write_error(UUID, "2", "get_thing_failure.log", "boom")
    assert path.split(UUID)[1] == bundle.split(UUID)[1] + "/get_thing_failure.log"
    errors.write_error(UUID, "2", "get_thing_failure.log", "boom again")
    assert errors.read_error(UUID, "2", "get_thing_failure.log") == "boom again"
    assert errors.list_errors(UUID, "2") == ["get_thing_failure.log"]
    assert errors.read_error(UUID, "3", "get_thing_failure.log") is None


def test_error_version_may_be_ahead_of_bundles(tmp_path):
    bundles, errors = LocalStorage(tmp_path / "b"), LocalErrorStorage(tmp_path / "e")
    bundles.write_bundle(UUID, "1", {"a.py": "x\n"})
    errors.write_error(UUID, "2", "a.py", "broken\n")  # version 2 failed; only v1 is stored
    assert bundles.get_latest(UUID) == "1" and errors.list_errors(UUID, "2") == ["a.py"]


def test_s3_keys_and_content_type():
    client = FakeS3()
    storage = S3ErrorStorage("err-bucket", client=client)
    uri = storage.write_error(UUID, "1", "t_failure.log", "x")
    assert uri == f"s3://err-bucket/{UUID}/1/t_failure.log"
    assert client.puts == [("err-bucket", f"{UUID}/1/t_failure.log", "text/plain")]
    assert storage.read_error(UUID, "1", "t_failure.log") == "x"
    assert storage.read_error(UUID, "1", "missing.log") is None
    assert storage.list_errors(UUID, "1") == ["t_failure.log"]


@pytest.mark.parametrize("uuid,version,name", [
    ("../x", "1", "a.log"), (UUID, "latest", "a.log"), (UUID, "1", "../a.log"), (UUID, "1", "a.exe"),
])
def test_invalid_inputs_rejected(tmp_path, uuid, version, name):
    with pytest.raises(ValueError):
        LocalErrorStorage(tmp_path).write_error(uuid, version, name, "x")


def test_get_error_storage_picks_by_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    monkeypatch.setenv("MODE", "local")
    assert isinstance(get_error_storage(), LocalErrorStorage)
    monkeypatch.setenv("MODE", "aws")
    monkeypatch.setenv("ERROR_S3_BUCKET", "err")
    monkeypatch.setattr("boto3.client", lambda *_: FakeS3())
    assert isinstance(get_error_storage(), S3ErrorStorage)


def _failing_run(cache, monkeypatch, errors, **kw):
    notified = []

    async def fake_notify(service, tool, report, **kwargs):
        notified.append(report)

    async def no_debug(*a, **k):
        return None

    monkeypatch.setattr(he, "notify_unresolved", fake_notify)
    monkeypatch.setattr(he, "debug_using_llm", no_debug)
    cache.set_source("demo_bistro", "get_thing", FAIL_SRC)
    out = asyncio.run(he.hit_endpoint(
        "demo_bistro", "get_thing", token="secret-dev", client=StubBedrock(), cache=cache,
        service_uuid=UUID, version="4", error_storage=errors, **kw,
    ))
    return out, notified


def test_hit_endpoint_stores_failure_under_version_before_notify(cache, monkeypatch, tmp_path):
    errors = LocalErrorStorage(tmp_path)
    out, notified = _failing_run(cache, monkeypatch, errors)
    assert out["status"] == "failed" and len(notified) == 1
    assert errors.read_error(UUID, "4", "get_thing_failure.log") == out["detail"]
    assert errors.read_error(UUID, "4", "get_thing.py") == FAIL_SRC


def test_hit_endpoint_storage_failure_does_not_break_notify(cache, monkeypatch):
    class Broken:
        def write_error(self, *a):
            raise RuntimeError("s3 down")

    out, notified = _failing_run(cache, monkeypatch, Broken())
    assert out["status"] == "failed" and len(notified) == 1


def test_hit_endpoint_verified_stores_no_error(cache, monkeypatch, tmp_path):
    errors = LocalErrorStorage(tmp_path)
    cache.set_source("demo_bistro", "get_thing", OK_SRC)
    out = asyncio.run(he.hit_endpoint(
        "demo_bistro", "get_thing", token="secret-dev", client=StubBedrock(), cache=cache,
        service_uuid=UUID, version="4", error_storage=errors,
    ))
    assert out == "verified" and errors.list_errors(UUID, "4") == []


def test_missing_token_failure_is_stored(monkeypatch, tmp_path):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.delenv("DEMO_BISTRO_DEV_TOKEN", raising=False)
    monkeypatch.setenv("GENERATED_DIR", "/nonexistent-dir")
    errors = LocalErrorStorage(tmp_path)
    out = asyncio.run(he.hit_endpoint(
        "demo_bistro", "get_thing", service_uuid=UUID, version="4", error_storage=errors,
    ))
    assert "demo_bistro_dev" in errors.read_error(UUID, "4", "get_thing_failure.log")
    assert out["status"] == "failed"
