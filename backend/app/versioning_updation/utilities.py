"""Stage and commit the next version of a service bundle.

Staging lives in Redis, keyed by the version being built (latest + 1):
    {service_uuid}:{next}          hash  file name -> content   (files to write)
    {service_uuid}:{next}_remove   set   file names             (files not to carry over)

Flow: add / replace / drop stage changes; create_version carries over every untouched file of
the current version (select), writes the new bundle as {service_uuid}/{next}, then clears both
caches. Versions are numeric here; a service whose latest version is a content hash starts at 1.
"""

import os

from backend.app.storage.add_n_read_mcp_tool import Storage, _check, get_storage

DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _redis():
    import redis

    return redis.Redis.from_url(os.environ.get("REDIS_URL", DEFAULT_REDIS_URL), decode_responses=True)


def _next_version(storage: Storage, service_uuid: str) -> str:
    latest = storage.get_latest(service_uuid)
    nxt = str(int(latest) + 1) if latest is not None and latest.isdigit() else "1"
    if storage.exists(service_uuid, nxt):
        raise ValueError(f"version {nxt} of {service_uuid} already exists")
    return nxt


class VersionBuilder:
    def __init__(self, storage: Storage | None = None, client=None):
        self.storage = storage or get_storage()
        self.client = client or _redis()

    def _keys(self, service_uuid: str) -> tuple[str, str, str]:
        nxt = _next_version(self.storage, service_uuid)
        return nxt, f"{service_uuid}:{nxt}", f"{service_uuid}:{nxt}_remove"

    def add(self, service_uuid: str, name: str, content: str) -> None:
        """Stage a new file for the next version."""
        _check(service_uuid, "1", {name: content})
        _, add_key, remove_key = self._keys(service_uuid)
        pipe = self.client.pipeline()
        pipe.hset(add_key, name, content)
        pipe.srem(remove_key, name)  # last operation wins
        pipe.execute()

    def replace(self, service_uuid: str, name: str, content: str) -> None:
        """Stage new content for `name` and mark the old copy as not to be carried over."""
        _check(service_uuid, "1", {name: content})
        _, add_key, remove_key = self._keys(service_uuid)
        pipe = self.client.pipeline()
        pipe.hset(add_key, name, content)
        pipe.sadd(remove_key, name)
        pipe.execute()

    def drop(self, service_uuid: str, name: str) -> None:
        """Leave `name` out of the next version."""
        _check(service_uuid, "1", {name: ""})
        _, add_key, remove_key = self._keys(service_uuid)
        pipe = self.client.pipeline()
        pipe.hdel(add_key, name)
        pipe.sadd(remove_key, name)
        pipe.execute()

    def select(self, service_uuid: str) -> None:
        """Carry over files of the current version that are neither staged nor removed."""
        _, add_key, remove_key = self._keys(service_uuid)
        latest = self.storage.get_latest(service_uuid)
        if latest is None:
            return
        base = self.storage.read_bundle(self.storage.bundle_path(service_uuid, latest))
        staged = set(self.client.hkeys(add_key))
        removed = set(self.client.smembers(remove_key))
        carried = {n: c for n, c in base.items() if n not in staged and n not in removed}
        if carried:
            self.client.hset(add_key, mapping=carried)

    def create_version(self, service_uuid: str) -> str:
        """Write the staged files as the next version, clear the caches, return its path."""
        nxt, add_key, remove_key = self._keys(service_uuid)
        self.select(service_uuid)
        files = self.client.hgetall(add_key)
        if not files:
            raise ValueError(f"nothing to write for {service_uuid} version {nxt}")
        path = self.storage.write_bundle(service_uuid, nxt, files)
        self.client.delete(add_key, remove_key)  # only after a successful write
        return path
