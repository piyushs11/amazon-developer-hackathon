import pytest

from backend.app.storage.add_n_read_mcp_tool import LocalStorage
from backend.versioning_updation.utilities import VersionBuilder

UUID = "11111111-1111-1111-1111-111111111111"


class FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def __getattr__(self, name):
        return lambda *a, **k: self.ops.append((name, a, k))

    def execute(self):
        for name, a, k in self.ops:
            getattr(self.r, name)(*a, **k)


class FakeRedis:
    def __init__(self):
        self.d = {}

    def pipeline(self):
        return FakePipe(self)

    def hset(self, key, name=None, value=None, mapping=None):
        h = self.d.setdefault(key, {})
        if name is not None:
            h[name] = value
        h.update(mapping or {})

    def hdel(self, key, name):
        self.d.get(key, {}).pop(name, None)

    def hkeys(self, key):
        return list(self.d.get(key, {}))

    def hgetall(self, key):
        return dict(self.d.get(key, {}))

    def sadd(self, key, name):
        self.d.setdefault(key, set()).add(name)

    def srem(self, key, name):
        self.d.get(key, set()).discard(name)

    def smembers(self, key):
        return set(self.d.get(key, set()))

    def delete(self, *keys):
        for k in keys:
            self.d.pop(k, None)


@pytest.fixture
def env(tmp_path):
    storage = LocalStorage(tmp_path / "bundles")
    redis = FakeRedis()
    return storage, redis, VersionBuilder(storage, redis)


def test_first_version_from_add(env):
    storage, redis, vb = env
    vb.add(UUID, "a.py", "1")
    path = vb.create_version(UUID)
    assert storage.read_bundle(path) == {"a.py": "1"}
    assert storage.get_latest(UUID) == "1"
    assert redis.d == {}


def test_next_version_carries_over_replaces_and_drops(env):
    storage, redis, vb = env
    storage.write_bundle(UUID, "1", {"a.py": "a", "b.py": "b", "c.py": "c"})
    vb.add(UUID, "d.py", "d")
    vb.replace(UUID, "a.py", "a2")
    vb.drop(UUID, "b.py")
    path = vb.create_version(UUID)
    assert path.endswith("/2")
    assert storage.read_bundle(path) == {"a.py": "a2", "c.py": "c", "d.py": "d"}
    assert storage.read_bundle(storage.bundle_path(UUID, "1")) == {"a.py": "a", "b.py": "b", "c.py": "c"}
    assert redis.d == {}


def test_last_operation_wins(env):
    storage, _, vb = env
    storage.write_bundle(UUID, "1", {"a.py": "a"})
    vb.drop(UUID, "a.py")
    vb.add(UUID, "a.py", "new")
    assert storage.read_bundle(vb.create_version(UUID)) == {"a.py": "new"}


def test_dropping_everything_raises_and_keeps_staging(env):
    storage, redis, vb = env
    storage.write_bundle(UUID, "1", {"a.py": "a"})
    vb.drop(UUID, "a.py")
    with pytest.raises(ValueError):
        vb.create_version(UUID)
    assert redis.d  # staging intact


def test_invalid_file_name_rejected(env):
    with pytest.raises(ValueError):
        env[2].add(UUID, "../x.py", "x")


def test_starts_at_one_after_hash_version(env):
    storage, _, vb = env
    storage.write_bundle(UUID, "abcdef012345", {"a.py": "a"})
    assert storage.read_bundle(vb.create_version(UUID)) == {"a.py": "a"}
    assert storage.get_latest(UUID) == "1"
