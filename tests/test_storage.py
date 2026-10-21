import io
import os

import pytest

from backend.app.storage.add_n_read_mcp_tool import LocalStorage, S3Storage, get_storage

UUID = "11111111-1111-1111-1111-111111111111"
VERSION = "abcdef012345"
FILES = {"get_thing.py": "x = 1\n", "demo_tools.py": "y = 2\n"}


def test_local_write_read_roundtrip_and_layout(tmp_path):
    storage = LocalStorage(tmp_path)
    path = storage.write_bundle(UUID, VERSION, FILES)
    assert path == str(tmp_path / UUID / VERSION)
    assert storage.exists(UUID, VERSION)
    assert storage.read_bundle(path) == FILES


def test_local_same_version_is_noop_and_other_version_untouched(tmp_path):
    storage = LocalStorage(tmp_path)
    first = storage.write_bundle(UUID, VERSION, FILES)
    again = storage.write_bundle(UUID, VERSION, {"get_thing.py": "CHANGED\n"})
    assert again == first and storage.read_bundle(first) == FILES  # never overwritten
    other = storage.write_bundle(UUID, "0123456789ab", {"get_thing.py": "v2\n"})
    assert other != first and storage.read_bundle(first) == FILES


def test_local_leaves_no_temp_folder_behind(tmp_path):
    LocalStorage(tmp_path).write_bundle(UUID, VERSION, FILES)
    assert [p.name for p in (tmp_path / UUID).iterdir()] == [VERSION]


@pytest.mark.parametrize(
    "uuid,version,files",
    [
        ("../etc", VERSION, FILES),
        (UUID, "XYZ", FILES),
        (UUID, VERSION, {"../evil.py": "x"}),
        (UUID, VERSION, {"Bad-Name.py": "x"}),
        (UUID, VERSION, {"notpython.txt": "x"}),
    ],
)
def test_invalid_names_rejected(tmp_path, uuid, version, files):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path).write_bundle(uuid, version, files)
    assert list(tmp_path.iterdir()) == []


def test_failed_write_leaves_no_partial_folder(tmp_path, monkeypatch):
    storage = LocalStorage(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(os, "rename", boom)
    with pytest.raises(RuntimeError):
        storage.write_bundle(UUID, VERSION, FILES)
    assert not storage.exists(UUID, VERSION)
    assert list((tmp_path / UUID).iterdir()) == []


def test_read_bundle_outside_root_rejected(tmp_path):
    with pytest.raises(ValueError):
        LocalStorage(tmp_path / "bundles").read_bundle(str(tmp_path))


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.stamps = {}
        self.puts = []
        self.clock = 0

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append((Bucket, Key, ContentType))
        self.objects[Key] = Body
        self.clock += 1
        self.stamps[Key] = self.clock  # stands in for LastModified

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000, **kwargs):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))[:MaxKeys]
        if not keys:
            return {"KeyCount": 0}
        return {"Contents": [{"Key": k, "LastModified": self.stamps[k]} for k in keys]}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


def test_s3_uses_same_keys_and_roundtrips():
    client = FakeS3()
    storage = S3Storage("my-bucket", client=client)
    path = storage.write_bundle(UUID, VERSION, FILES)
    assert path == f"s3://my-bucket/bundles/{UUID}/{VERSION}/"
    assert sorted(k for _, k, _ in client.puts) == [
        f"bundles/{UUID}/{VERSION}/demo_tools.py", f"bundles/{UUID}/{VERSION}/get_thing.py",
    ]
    assert storage.exists(UUID, VERSION)
    assert storage.read_bundle(path) == FILES
    storage.write_bundle(UUID, VERSION, {"get_thing.py": "CHANGED"})  # immutable: no new puts
    assert len(client.puts) == 2


def test_s3_rejects_foreign_paths():
    storage = S3Storage("my-bucket", client=FakeS3())
    with pytest.raises(ValueError):
        storage.read_bundle("s3://other-bucket/bundles/x/abcdef012345/")


def test_s3_read_bundle_accepts_numeric_version():
    storage = S3Storage("my-bucket", client=FakeS3())
    path = storage.write_bundle(UUID, "1", FILES)
    assert path == f"s3://my-bucket/bundles/{UUID}/1/"
    assert storage.read_bundle(path) == FILES


def test_s3_read_bundle_rejects_bad_version():
    storage = S3Storage("my-bucket", client=FakeS3())
    for bad in ("latest", "ABCDEF012345", "1234567890"):  # not hex-12, not 1-9 digits
        with pytest.raises(ValueError):
            storage.read_bundle(f"s3://my-bucket/bundles/{UUID}/{bad}/")


def test_get_storage_picks_by_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    monkeypatch.delenv("MODE", raising=False)
    assert isinstance(get_storage(), LocalStorage)
    monkeypatch.setenv("MODE", "aws")
    monkeypatch.setattr(S3Storage, "from_env", classmethod(lambda cls: cls("b", client=FakeS3())))
    assert isinstance(get_storage(), S3Storage)


def test_s3_mapped_json_key_and_roundtrip():
    client = FakeS3()
    storage = S3Storage("my-bucket", client=client)
    assert storage.read_mapped(UUID) is None
    path = storage.write_mapped(UUID, {"service_uuid": UUID})
    assert path == f"s3://my-bucket/mapped/mapped.{UUID}.json"
    assert list(client.objects) == [f"mapped/mapped.{UUID}.json"]
    assert storage.read_mapped(UUID) == {"service_uuid": UUID}
    with pytest.raises(ValueError):
        storage.read_mapped("../x")


V1, V2 = "aaaaaaaaaaaa", "bbbbbbbbbbbb"


def test_local_get_latest_picks_the_newest_version_and_read_file(tmp_path):
    storage = LocalStorage(tmp_path)
    assert storage.get_latest(UUID) is None
    p1 = storage.write_bundle(UUID, V1, {"get_thing.py": "one\n"})
    p2 = storage.write_bundle(UUID, V2, {"get_thing.py": "two\n"})
    os.utime(p1, ns=(1_000_000_000, 1_000_000_000))
    os.utime(p2, ns=(2_000_000_000, 2_000_000_000))
    assert storage.get_latest(UUID) == V2
    os.utime(p1, ns=(3_000_000_000, 3_000_000_000))  # v1 rewritten later: now the newest
    assert storage.get_latest(UUID) == V1
    assert storage.read_file(UUID, V2, "get_thing.py") == "two\n"
    assert storage.read_file(UUID, V2, "missing.py") is None
    assert storage.read_file(UUID, "cccccccccccc", "get_thing.py") is None
    with pytest.raises(ValueError):
        storage.read_file(UUID, V2, "../x.py")
    with pytest.raises(ValueError):
        storage.get_latest("../x")


def test_s3_get_latest_and_read_file():
    storage = S3Storage("my-bucket", client=FakeS3())
    assert storage.get_latest(UUID) is None
    storage.write_bundle(UUID, V1, {"get_thing.py": "one"})
    storage.write_bundle(UUID, V2, {"get_thing.py": "two"})
    assert storage.get_latest(UUID) == V2
    assert storage.read_file(UUID, V1, "get_thing.py") == "one"
    assert storage.read_file(UUID, V1, "missing.py") is None
