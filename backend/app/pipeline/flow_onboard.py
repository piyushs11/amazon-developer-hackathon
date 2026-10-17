"""Onboard flow: generate (create_folders.sh) -> seed the Redis tool cache -> verify -> store.

Input is the mapped service (C2 dict). A failing tool is patched in the cache by
debug_using_llm (verifier/patch_issue.py) and retried inside hit_endpoint. Only verified tools
are written to storage, together with the consolidated <service>_tools.py, under
bundles/{service_uuid}/{version}/.
"""

import ast
import hashlib
import json
import subprocess
from pathlib import Path

from jinja2 import Template

from backend.app.codegen.templates.services_consolidation_template import SERVICE_TEMPLATE
from backend.app.codegen.verifier.utilities import service_slug, verify_service
from backend.app.storage.add_n_read_mcp_tool import Storage, get_storage
from backend.app.storage.tool_cache import ToolCache
from backend.versioning_updation.utilities import _next_version

CREATE_FOLDERS = Path(__file__).resolve().parents[1] / "codegen" / "create_folders.sh"
MAX_MESSAGE = 300


class OnboardStepError(Exception):
    """A pipeline step failed. `step` is a C6 StepError step ("codegen" or "store")."""

    def __init__(self, step: str, code: str, message: str):
        super().__init__(message)
        self.step = step
        self.code = code
        self.message = message


def _short(e: Exception) -> str:
    if isinstance(e, subprocess.CalledProcessError):
        text = (e.stderr or "").strip() or f"exit status {e.returncode}"
    else:
        text = str(e)
    return text[:MAX_MESSAGE]


def generate(mapped: dict, out_dir: str) -> None:
    """Render the service folder with create_folders.sh, feeding it the mapped JSON on stdin."""
    subprocess.run(
        ["bash", str(CREATE_FOLDERS), "-", out_dir],
        input=json.dumps(mapped), text=True, check=True, capture_output=True,
    )


def seed_cache(service_name: str, mapped: dict, out_dir: str, cache: ToolCache) -> list[str]:
    """Load each generated tool file and its endpoint JSON into the cache. Returns tool names."""
    tool_names = []
    for endpoint in mapped["endpoints"]:
        tool_name = endpoint.get("tool_name") or endpoint["endpoint_id"]
        source = (Path(out_dir) / service_name / f"{tool_name}.py").read_text()
        cache.set_source(service_name, tool_name, source)
        cache.set_endpoint(service_name, tool_name, endpoint)
        tool_names.append(tool_name)
    return tool_names


def compute_version(files: dict[str, str]) -> str:
    """First 12 hex chars of a sha256 over the files (sorted by name): same files, same version."""
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b"\0" + files[name].encode() + b"\0")
    return digest.hexdigest()[:12]


def persist_verified(
    service_name: str, service_uuid: str, results: dict, cache: ToolCache, storage: Storage,
    version: str | None = None,
) -> dict:
    """Write the verified tools (latest cached source) + <service>_tools.py to storage.

    Returns {"bundle_path", "version", "stored", "skipped"}; nothing is written if no tool
    verified.
    """
    stored = [t for t, r in results.items() if r["status"] == "pass"]
    skipped = [t for t in results if t not in stored]
    if not stored:
        return {"bundle_path": None, "version": None, "stored": [], "skipped": skipped}

    files = {}
    endpoints = []
    for tool_name in stored:
        files[f"{tool_name}.py"] = cache.get_source(service_name, tool_name)
        endpoint = cache.get_endpoint(service_name, tool_name) or {}
        endpoints.append({"tool_name": tool_name, "read_only": bool(endpoint.get("read_only", False))})
    files[f"{service_name}_tools.py"] = Template(SERVICE_TEMPLATE).render(
        service_name=service_name, endpoints=endpoints
    )
    for name, source in files.items():
        ast.parse(source, filename=name)  # never store code that does not parse

    version = version or compute_version(files)
    path = storage.write_bundle(service_uuid, version, files)
    return {"bundle_path": path, "version": version, "stored": stored, "skipped": skipped}


async def onboard(
    mapped: dict, out_dir: str, *, cache: ToolCache | None = None,
    storage: Storage | None = None, **verify_kwargs,
) -> dict:
    """Generate the service folder, seed the cache, verify each tool, store the verified ones.

    Raises OnboardStepError(step="codegen" | "store", ...) if a step itself breaks (as opposed
    to individual tools failing verification, which is reported in the result).
    """
    cache = cache or ToolCache.from_env()
    storage = storage or get_storage()
    service_uuid = mapped["service_uuid"]
    version_new = _next_version(storage, service_uuid)  # one version for the bundle or, on failure, the error files
    try:
        service_name = service_slug(mapped["service_name"])
        generate(mapped, out_dir)
        tool_names = seed_cache(service_name, mapped, out_dir, cache)
        results = await verify_service(
            service_name, tool_names, cache=cache, service_uuid=service_uuid, version=version_new,
            **verify_kwargs
        )
    except Exception as e:
        raise OnboardStepError("codegen", type(e).__name__, _short(e)) from e
    try:
        stored = persist_verified(service_name, service_uuid, results, cache, storage, version_new)
    except Exception as e:
        raise OnboardStepError("store", type(e).__name__, _short(e)) from e
    ok = bool(results) and all(r["status"] == "pass" for r in results.values())
    return {"status": "ok" if ok else "failed", "results": results, **stored}
