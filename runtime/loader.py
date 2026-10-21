"""Dev 3: load a published bundle's tools, cached by (service_uuid, version).

Bundle layout (written by Dev 2's pipeline, bundles/{service_uuid}/{version}/):
    <tool_name>.py        one tool: an async `<tool_name>for<service>(...)` function that takes
                          no token argument and reads it with runtime.auth_context.get_current_token()
    <service>_tools.py    consolidation file (TOOLS list + readOnlyHint annotations)

The gateway only needs the tool files, so each one is compiled into its own in-memory module
(same rule as Dev 2's verifier). <service>_tools.py is read as text for the readOnlyHint
annotations but never imported (it pulls in an MCP server we don't run here).
A new version is a new cache key, so it is used on the next call without a restart.
"""
from __future__ import annotations

import inspect
import re
import threading
import types
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

_FILE = re.compile(r"^([a-z_][a-z0-9_]*)\.py$")
_READ_ONLY = re.compile(r"readOnlyHint\"?'?\s*:\s*(True|False)\s*\}\s*\)\s*\(\s*(\w+)\s*\)")
_ARG_DOC = re.compile(r"^\s{4}(\w+):\s*(.+)$", re.MULTILINE)
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
               list: "array", dict: "object"}


class BundleLoadError(Exception):
    pass


class BundleReader(Protocol):  # Dev 2's Storage satisfies this
    def read_bundle(self, path: str) -> dict[str, str]: ...


class Tool:
    def __init__(self, name: str, fn: Callable, input_schema: dict, description: str,
                 read_only: bool | None):
        self.name = name  # MCP tool name = file name, e.g. "get_order_status"
        self.fn = fn  # e.g. get_order_statusfordemo_bistro
        self.input_schema = input_schema
        self.description = description
        self.read_only = read_only


class LoadedBundle:
    def __init__(self, service_name: str | None, tools: list[Tool]):
        self.service_name = service_name  # slug from <service>_tools.py, e.g. "demo_bistro"
        self.tools = tools
        self.by_name = {t.name: t for t in tools}


_cache: dict[tuple[str, str], LoadedBundle] = {}
_lock = threading.Lock()
_reader: BundleReader | None = None


def set_reader(reader: BundleReader | None) -> None:
    """Inject Dev 2's Storage for s3:// bundle paths (MODE=aws). Local paths are read directly."""
    global _reader
    _reader = reader


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
    if bundle_path.startswith("s3://"):
        if _reader is None:
            raise BundleLoadError("s3:// bundle path but no storage reader configured")
        return _reader.read_bundle(bundle_path)
    root = Path(bundle_path)
    if not root.is_dir():
        raise BundleLoadError(f"bundle folder not found: {bundle_path}")
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(root.iterdir()) if p.is_file()}


def _load_uncached(service_uuid: str, version: str, bundle_path: str) -> LoadedBundle:
    try:
        files = _read_files(bundle_path)
    except BundleLoadError:
        raise
    except Exception as exc:  # storage errors (S3, permissions, bad path)
        raise BundleLoadError(f"could not read bundle: {type(exc).__name__}: {exc}") from exc

    consolidation = {n: s for n, s in files.items() if n.endswith("_tools.py")}
    tool_files = {n: s for n, s in files.items() if _FILE.match(n) and n not in consolidation}
    if not tool_files:
        raise BundleLoadError("bundle has no tool files")

    service_name = None
    read_only: dict[str, bool] = {}
    for name, source in consolidation.items():
        service_name = name.removesuffix("_tools.py")
        read_only.update({fn: flag == "True" for flag, fn in _READ_ONLY.findall(source)})

    tag = re.sub(r"[^A-Za-z0-9]", "_", f"{service_uuid}_{version}")
    tools = []
    for file_name, source in tool_files.items():
        tool_name = _FILE.match(file_name).group(1)
        fn = load_tool_source(source, tool_name, module_name=f"_mcpb_{tag}_{tool_name}")
        description, schema = _describe(fn)
        tools.append(Tool(tool_name, fn, schema, description, read_only.get(fn.__name__)))
    return LoadedBundle(service_name, tools)


def load_tool_source(source: str, tool_name: str, module_name: str | None = None) -> Callable:
    """Compile one tool file and return its tool function.

    Also usable as Dev 2's `tool_loader(source, tool_name)` in runtime/client.py.
    """
    module = types.ModuleType(module_name or f"_mcpb_tool_{tool_name}")
    try:
        exec(compile(source, f"<{tool_name}.py>", "exec"), module.__dict__)  # noqa: S102 - generated by us
    except Exception as exc:  # syntax errors, bad imports in generated code
        raise BundleLoadError(f"{tool_name}.py failed to load: {type(exc).__name__}: {exc}") from exc
    for name, fn in inspect.getmembers(module, inspect.iscoroutinefunction):
        if fn.__module__ == module.__name__ and not name.startswith("_") \
                and not name.endswith("_request"):
            if "token" in inspect.signature(fn).parameters:
                raise BundleLoadError(f"{tool_name}: tool function must not take a token argument")
            return fn
    raise BundleLoadError(f"{tool_name}.py has no tool function")


def _describe(fn: Callable) -> tuple[str, dict]:
    """Description + JSON input schema from the function signature and its docstring."""
    doc = inspect.getdoc(fn) or ""
    arg_docs = {m.group(1): m.group(2).strip() for m in _ARG_DOC.finditer(doc)}
    hints = typing.get_type_hints(fn)
    props, required = {}, []
    for name, param in inspect.signature(fn).parameters.items():
        ann = hints.get(name, str)
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        base = typing.get_origin(ann) if typing.get_origin(ann) in (list, dict) else (
            args[0] if args else ann)
        props[name] = {"type": _JSON_TYPES.get(base, "string"),
                       "description": arg_docs.get(name, name)}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return doc.split("\n\n")[0].strip(), {"type": "object", "properties": props,
                                           "required": required}
