"""Redis cache for generated tool sources and their endpoint JSON.

Keys (per service + tool):
    {prefix}:{service}:{tool}:src       current tool source
    {prefix}:{service}:{tool}:prev      previous source (backup, written on every update)
    {prefix}:{service}:{tool}:endpoint  one C2 MappedService endpoint entry (JSON)
"""

import json
import os
import re

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _check(**names: str) -> None:
    for label, value in names.items():
        if not isinstance(value, str) or not _IDENT.match(value):
            raise ValueError(f"invalid {label}: {value!r}")


class ToolCache:
    def __init__(self, client, prefix: str = "tool"):
        self.client = client
        self.prefix = prefix

    @classmethod
    def from_env(cls, prefix: str = "tool") -> "ToolCache":
        import redis

        url = os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
        return cls(redis.Redis.from_url(url, decode_responses=True), prefix)

    def _key(self, service: str, tool: str, kind: str) -> str:
        _check(service=service, tool=tool)
        return f"{self.prefix}:{service}:{tool}:{kind}"

    def get_source(self, service: str, tool: str) -> str | None:
        return self.client.get(self._key(service, tool, "src"))

    def get_previous_source(self, service: str, tool: str) -> str | None:
        return self.client.get(self._key(service, tool, "prev"))

    def set_source(self, service: str, tool: str, source: str) -> None:
        """Store `source`, keeping the version it replaces as the `prev` backup."""
        src_key = self._key(service, tool, "src")
        current = self.client.get(src_key)
        pipe = self.client.pipeline()
        if current is not None:
            pipe.set(self._key(service, tool, "prev"), current)
        pipe.set(src_key, source)
        pipe.execute()

    def get_endpoint(self, service: str, tool: str) -> dict | None:
        raw = self.client.get(self._key(service, tool, "endpoint"))
        return json.loads(raw) if raw else None

    def set_endpoint(self, service: str, tool: str, endpoint: dict) -> None:
        self.client.set(self._key(service, tool, "endpoint"), json.dumps(endpoint))

    def delete_all(self) -> None:
        """Remove every key under this cache's prefix (used by tests)."""
        for key in self.client.scan_iter(f"{self.prefix}:*"):
            self.client.delete(key)
