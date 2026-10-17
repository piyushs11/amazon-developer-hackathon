"""Dev 3: load a bundle's TOOLS, cached by (service_uuid, version).

A bundle (C3) is a folder with manifest.json, tools.py and endpoints/. It is copied
into a local cache dir and imported as its own package, so two versions of the
same service (or two services) never share module objects. A new version is a
new cache key, so it is picked up on the next call without a restart.
"""
from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import inspect
import json
import os
import re
import shutil
import sys
import threading
import uuid as uuid_lib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from runtime import RUNTIME_VERSION

Tool = tuple[dict, Callable]


class BundleLoadError(Exception):
    pass


class BundleReader(Protocol):  # Dev 2's Storage satisfies this
    def read_bundle(self, path: str) -> dict[str, str]: ...


class LoadedBundle:
    def __init__(self, manifest: dict, tools: list[Tool]):
        self.manifest = manifest
        self.tools = tools
        self.by_name = {tool["name"]: (tool, run) for tool, run in tools}


_cache: dict[tuple[str, str], LoadedBundle] = {}
_lock = threading.Lock()
_reader: BundleReader | None = None


def set_reader(reader: BundleReader | None) -> None:
    """Inject Dev 2's Storage (local or S3). Without one, bundle_path is a local folder."""
    global _reader
    _reader = reader


def cache_dir() -> Path:
    return Path(os.getenv("BUNDLE_CACHE_DIR", ".cache/bundles"))


def load(service_uuid: str, version: str, bundle_path: str) -> LoadedBundle:
    key = (service_uuid, version)
    if key in _cache:
        return _cache[key]
    with _lock:
        if key not in _cache:
            _cache[key] = _load_uncached(service_uuid, version, bundle_path)
        return _cache[key]


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _read_files(bundle_path: str) -> dict[str, str]:
    if _reader is not None:
        return _reader.read_bundle(bundle_path)
    root = Path(bundle_path)
    if not root.is_dir():
        raise BundleLoadError(f"bundle folder not found: {bundle_path}")
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def _module_name(service_uuid: str, version: str) -> str:
    try:
        uuid_hex = uuid_lib.UUID(service_uuid).hex
    except ValueError as exc:
        raise BundleLoadError(f"bad service_uuid: {service_uuid!r}") from exc
    return f"_mcpb_u{uuid_hex}_v{re.sub(r'[^A-Za-z0-9]', '_', version)}"


def _load_uncached(service_uuid: str, version: str, bundle_path: str) -> LoadedBundle:
    name = _module_name(service_uuid, version)
    files = _read_files(bundle_path)
    if "manifest.json" not in files or "tools.py" not in files:
        raise BundleLoadError("bundle must contain manifest.json and tools.py")
    try:
        manifest = json.loads(files["manifest.json"])
    except json.JSONDecodeError as exc:
        raise BundleLoadError("manifest.json is not valid JSON") from exc
    if str(manifest.get("runtime_version")) != RUNTIME_VERSION:
        raise BundleLoadError(
            f"bundle runtime_version {manifest.get('runtime_version')!r} "
            f"!= running runtime {RUNTIME_VERSION!r}"
        )
    if manifest.get("service_uuid") not in (None, service_uuid):
        raise BundleLoadError("manifest service_uuid does not match")

    target = cache_dir() / service_uuid / version
    _write_cache(target, files)

    # Register the bundle folder as a package, then import its tools module.
    _forget(name)  # drop stale submodules if this version was loaded before a cache clear
    pkg_spec = importlib.machinery.ModuleSpec(name, None, is_package=True)
    pkg_spec.submodule_search_locations = [str(target.resolve())]
    pkg = importlib.util.module_from_spec(pkg_spec)
    pkg.__path__ = [str(target.resolve())]
    sys.modules[name] = pkg
    try:
        tools_mod = importlib.import_module(f"{name}.tools")
        tools = _validate(getattr(tools_mod, "TOOLS", None))
    except BundleLoadError:
        _forget(name)
        raise
    except Exception as exc:  # syntax errors, bad imports, ... in generated code
        _forget(name)
        raise BundleLoadError(f"bundle failed to import: {type(exc).__name__}: {exc}") from exc
    return LoadedBundle(manifest, tools)


def _write_cache(target: Path, files: dict[str, str]) -> None:
    # Versions are immutable, but rewrite anyway: a half-written cache dir must not stick.
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    for rel, content in files.items():
        dest = (tmp / rel).resolve()
        if not dest.is_relative_to(tmp.resolve()):
            raise BundleLoadError(f"bundle file escapes its folder: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)


def _forget(name: str) -> None:
    for mod in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[mod]


def _validate(tools) -> list[Tool]:
    if not isinstance(tools, list) or not tools:
        raise BundleLoadError("tools.py must define a non-empty TOOLS list")
    seen: set[str] = set()
    for entry in tools:
        if not (isinstance(entry, tuple) and len(entry) == 2):
            raise BundleLoadError("each TOOLS entry must be a (TOOL, run) pair")
        tool, run = entry
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            raise BundleLoadError("TOOL must be a dict with a name")
        if not isinstance(tool.get("input_schema"), dict):
            raise BundleLoadError(f"tool {tool['name']} has no input_schema")
        if not inspect.iscoroutinefunction(run):
            raise BundleLoadError(f"tool {tool['name']}: run must be an async function")
        if tool["name"] in seen:
            raise BundleLoadError(f"duplicate tool name {tool['name']}")
        seen.add(tool["name"])
    return list(tools)
