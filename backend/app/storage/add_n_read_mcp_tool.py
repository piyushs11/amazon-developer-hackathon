"""Durable storage for verified service bundles (local folder now, S3 in MODE=aws).

Layout (identical keys for both backends):
    bundles/{service_uuid}/{version}/{file}.py     verified tool bundles (immutable versions)
    mapped/mapped.{service_uuid}.json              the mapped service JSON (C2) for a service

A bundle version folder is immutable: writing a version that already exists is a no-op that
returns the existing path.
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

_UUID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_VERSION_PATTERN = r"[0-9a-f]{12}|[0-9]{1,9}"  # content hash, or numeric (versioning_updation)
_VERSION = re.compile(rf"^({_VERSION_PATTERN})$")
# s3://{bucket}/bundles/{service_uuid}/{version}/ ; group 1 = bucket, group 2 = key prefix
_S3_BUNDLE_PATH = re.compile(
    rf"^s3://([^/]+)/(bundles/[A-Za-z0-9-]{{1,64}}/(?:{_VERSION_PATTERN})/)$"
)
_FILE = re.compile(r"^[a-z_][a-z0-9_]*\.py$")


def _check_uuid(service_uuid: str) -> None:
    if not isinstance(service_uuid, str) or not _UUID.match(service_uuid):
        raise ValueError(f"invalid service_uuid: {service_uuid!r}")


def _mapped_name(service_uuid: str) -> str:
    _check_uuid(service_uuid)
    return f"mapped.{service_uuid}.json"


def _check(service_uuid: str, version: str, files: dict[str, str] | None = None) -> None:
    _check_uuid(service_uuid)
    if not isinstance(version, str) or not _VERSION.match(version):
        raise ValueError(f"invalid version: {version!r}")
    for name in files or {}:
        if not _FILE.match(name):
            raise ValueError(f"invalid file name: {name!r}")


class Storage(Protocol):
    def write_bundle(self, service_uuid: str, version: str, files: dict[str, str]) -> str: ...
    def read_bundle(self, path: str) -> dict[str, str]: ...
    def exists(self, service_uuid: str, version: str) -> bool: ...
    def bundle_path(self, service_uuid: str, version: str) -> str: ...
    def read_mapped(self, service_uuid: str) -> dict | None: ...
    def write_mapped(self, service_uuid: str, data: dict) -> str: ...
    def get_latest(self, service_uuid: str) -> str | None: ...
    def read_file(self, service_uuid: str, version: str, name: str) -> str | None: ...


class LocalStorage:
    def __init__(self, root, mapped_root=None):
        self.root = Path(root)
        self.mapped_root = Path(mapped_root) if mapped_root else self.root.parent / "mapped"

    @classmethod
    def from_env(cls) -> "LocalStorage":
        base = Path(os.environ.get("GENERATED_DIR", "generated"))
        return cls(base / "bundles", base / "mapped")

    def _dir(self, service_uuid: str, version: str) -> Path:
        _check(service_uuid, version)
        return self.root / service_uuid / version

    def exists(self, service_uuid: str, version: str) -> bool:
        return self._dir(service_uuid, version).is_dir()

    def bundle_path(self, service_uuid: str, version: str) -> str:
        return str(self._dir(service_uuid, version))

    def write_bundle(self, service_uuid: str, version: str, files: dict[str, str]) -> str:
        _check(service_uuid, version, files)
        dest = self._dir(service_uuid, version)
        if dest.exists():
            return str(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".tmp-"))
        try:
            for name, content in files.items():
                (tmp / name).write_text(content)
            os.rename(tmp, dest)  # atomic: readers see the whole folder or nothing
        except OSError:
            shutil.rmtree(tmp, ignore_errors=True)
            if not dest.exists():
                raise
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return str(dest)

    def read_bundle(self, path: str) -> dict[str, str]:
        folder = Path(path).resolve()
        if not folder.is_relative_to(self.root.resolve()):
            raise ValueError(f"path is outside the storage root: {path!r}")
        return {p.name: p.read_text() for p in sorted(folder.iterdir()) if p.is_file()}

    def get_latest(self, service_uuid: str) -> str | None:
        """The most recently written version of a service's bundle, or None if it has none."""
        _check_uuid(service_uuid)
        folder = self.root / service_uuid
        if not folder.is_dir():
            return None
        versions = [p for p in folder.iterdir() if p.is_dir() and _VERSION.match(p.name)]
        newest = max(versions, key=lambda p: (p.stat().st_mtime_ns, p.name), default=None)
        return newest.name if newest else None

    def read_file(self, service_uuid: str, version: str, name: str) -> str | None:
        """One file of a stored bundle, or None if it does not exist."""
        _check(service_uuid, version, {name: ""})
        path = self._dir(service_uuid, version) / name
        return path.read_text() if path.is_file() else None

    def read_mapped(self, service_uuid: str) -> dict | None:
        """The stored mapped JSON, or None if nothing is stored. Invalid JSON raises ValueError."""
        path = self.mapped_root / _mapped_name(service_uuid)
        return json.loads(path.read_text()) if path.is_file() else None

    def write_mapped(self, service_uuid: str, data: dict) -> str:
        path = self.mapped_root / _mapped_name(service_uuid)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)  # atomic
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return str(path)


class S3Storage:
    """Same keys as LocalStorage under s3://{bucket}/... (used when MODE=aws)."""

    def __init__(self, bucket: str, client=None):
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client("s3")
        self.client = client

    @classmethod
    def from_env(cls) -> "S3Storage":
        return cls(os.environ["S3_BUCKET"])

    @staticmethod
    def _prefix(service_uuid: str, version: str) -> str:
        _check(service_uuid, version)
        return f"bundles/{service_uuid}/{version}/"

    def _list(self, prefix: str, max_keys: int = 1000) -> list[str]:
        resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=max_keys)
        return [obj["Key"] for obj in resp.get("Contents", [])]

    def bundle_path(self, service_uuid: str, version: str) -> str:
        return f"s3://{self.bucket}/{self._prefix(service_uuid, version)}"

    def exists(self, service_uuid: str, version: str) -> bool:
        return bool(self._list(self._prefix(service_uuid, version), max_keys=1))

    def write_bundle(self, service_uuid: str, version: str, files: dict[str, str]) -> str:
        _check(service_uuid, version, files)
        prefix = self._prefix(service_uuid, version)
        if not self.exists(service_uuid, version):
            for name, content in files.items():
                self.client.put_object(
                    Bucket=self.bucket, Key=prefix + name, Body=content.encode(),
                    ContentType="text/x-python",
                )
        return f"s3://{self.bucket}/{prefix}"

    def read_bundle(self, path: str) -> dict[str, str]:
        match = _S3_BUNDLE_PATH.match(path)
        if not match or match.group(1) != self.bucket:
            raise ValueError(f"not a bundle path in bucket {self.bucket!r}: {path!r}")
        prefix = match.group(2)
        out = {}
        for key in self._list(prefix):
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            out[key[len(prefix):]] = body.decode()
        return out

    def get_latest(self, service_uuid: str) -> str | None:
        """The version whose objects were written most recently, or None if there is none."""
        _check_uuid(service_uuid)
        prefix = f"bundles/{service_uuid}/"
        newest: dict[str, object] = {}
        kwargs = {"Bucket": self.bucket, "Prefix": prefix}
        while True:
            resp = self.client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                version = obj["Key"][len(prefix):].split("/", 1)[0]
                if _VERSION.match(version) and (version not in newest or obj["LastModified"] > newest[version]):
                    newest[version] = obj["LastModified"]
            if not resp.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = resp["NextContinuationToken"]
        return max(newest, key=lambda v: (newest[v], v), default=None)

    def read_file(self, service_uuid: str, version: str, name: str) -> str | None:
        _check(service_uuid, version, {name: ""})
        key = self._prefix(service_uuid, version) + name
        if key not in self._list(key, max_keys=1):
            return None
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read().decode()

    def read_mapped(self, service_uuid: str) -> dict | None:
        key = f"mapped/{_mapped_name(service_uuid)}"
        if key not in self._list(key, max_keys=1):
            return None
        return json.loads(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())

    def write_mapped(self, service_uuid: str, data: dict) -> str:
        key = f"mapped/{_mapped_name(service_uuid)}"
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=json.dumps(data).encode(), ContentType="application/json"
        )
        return f"s3://{self.bucket}/{key}"


def get_storage() -> Storage:
    return S3Storage.from_env() if os.environ.get("MODE", "local") == "aws" else LocalStorage.from_env()
