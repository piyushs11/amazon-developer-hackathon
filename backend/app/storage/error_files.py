"""Durable storage for files of versions that failed verification (local folder now, S3 in MODE=aws).

Parallel to add_n_read_mcp_tool.py, with the same folder structure so a failing version can be
debugged next to its bundle:
    {service_uuid}/{version}/{file}     (bucket ERROR_S3_BUCKET, or $GENERATED_DIR/errors/ locally)

The version is the pending `version_new` the caller already holds: the same one that
write_bundle uses when verification passes. Unlike bundles, error files are overwritable
(retries rewrite the same names).
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from backend.app.storage.add_n_read_mcp_tool import _VERSION, _check_uuid

_FILE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*\.(py|json|txt|log)$")
_CONTENT_TYPES = {"py": "text/x-python", "json": "application/json", "txt": "text/plain", "log": "text/plain"}


def _check(service_uuid: str, version: str, name: str | None = None) -> None:
    _check_uuid(service_uuid)
    if not isinstance(version, str) or not _VERSION.match(version):
        raise ValueError(f"invalid version: {version!r}")
    if name is not None and (not _FILE.match(name) or ".." in name):
        raise ValueError(f"invalid file name: {name!r}")


class ErrorStorage(Protocol):
    def write_error(self, service_uuid: str, version: str, name: str, content: str) -> str: ...
    def read_error(self, service_uuid: str, version: str, name: str) -> str | None: ...
    def list_errors(self, service_uuid: str, version: str) -> list[str]: ...


class LocalErrorStorage:
    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def from_env(cls) -> "LocalErrorStorage":
        return cls(Path(os.environ.get("GENERATED_DIR", "generated")) / "errors")

    def _dir(self, service_uuid: str, version: str) -> Path:
        _check(service_uuid, version)
        return self.root / service_uuid / version

    def write_error(self, service_uuid: str, version: str, name: str, content: str) -> str:
        _check(service_uuid, version, name)
        folder = self._dir(service_uuid, version)
        folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            os.replace(tmp, folder / name)  # atomic overwrite
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return str(folder / name)

    def read_error(self, service_uuid: str, version: str, name: str) -> str | None:
        _check(service_uuid, version, name)
        path = self._dir(service_uuid, version) / name
        return path.read_text() if path.is_file() else None

    def list_errors(self, service_uuid: str, version: str) -> list[str]:
        folder = self._dir(service_uuid, version)
        if not folder.is_dir():
            return []
        return sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(".tmp-"))


class S3ErrorStorage:
    """Same keys as LocalErrorStorage under s3://{bucket}/... (used when MODE=aws)."""

    def __init__(self, bucket: str, client=None):
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client("s3")
        self.client = client

    @classmethod
    def from_env(cls) -> "S3ErrorStorage":
        return cls(os.environ["ERROR_S3_BUCKET"])

    @staticmethod
    def _prefix(service_uuid: str, version: str) -> str:
        _check(service_uuid, version)
        return f"{service_uuid}/{version}/"

    def write_error(self, service_uuid: str, version: str, name: str, content: str) -> str:
        _check(service_uuid, version, name)
        key = self._prefix(service_uuid, version) + name
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=content.encode(),
            ContentType=_CONTENT_TYPES[name.rsplit(".", 1)[1]],
        )
        return f"s3://{self.bucket}/{key}"

    def _keys(self, prefix: str, max_keys: int = 1000) -> list[str]:
        resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=max_keys)
        return [obj["Key"] for obj in resp.get("Contents", [])]

    def read_error(self, service_uuid: str, version: str, name: str) -> str | None:
        _check(service_uuid, version, name)
        key = self._prefix(service_uuid, version) + name
        if key not in self._keys(key, max_keys=1):
            return None
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read().decode()

    def list_errors(self, service_uuid: str, version: str) -> list[str]:
        prefix = self._prefix(service_uuid, version)
        return sorted(k[len(prefix):] for k in self._keys(prefix))


def get_error_storage() -> ErrorStorage:
    mode = os.environ.get("MODE", "local")
    return S3ErrorStorage.from_env() if mode == "aws" else LocalErrorStorage.from_env()
