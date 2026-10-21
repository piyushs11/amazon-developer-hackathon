"""Verify ONE generated tool of a service by letting an LLM call it.

hit_endpoint(service_name, tool_name) loads the tool from the Redis tool cache
(tool_details), asks Bedrock to invent a fake use case and call it, records
{input, output, error}, and classifies it (parse_response). A failure is turned into a report
for debug_using_llm (which patches the cached source) and retried, up to MAX_ATTEMPTS times,
then notify_unresolved is triggered.
Returns "verified" on success, otherwise {"status": "failed", "detail": <last report>}.
"""

import asyncio
import hashlib
import inspect
import json
import os
import re
import types
import typing
from dataclasses import dataclass

from backend.app.storage.read_cred_tokens import dev_key, get_dev_token
from backend.app.storage.tool_cache import ToolCache
from runtime.auth_context import call_with_token

from .patch_issue import PatchInputError, debug_using_llm
from .utilities import DEFAULT_MODEL_ID, bedrock_client, notify_unresolved, store_failure

CALL_TIMEOUT = 10
MAX_DETAIL = 300
MAX_ATTEMPTS = 5
TEST_SUFFIX = " Call this tool for the testing."

VERIFIED = "verified"
RESPONSE_GENERATED = "response_generated"
ERROR = "error"

TEST_PROMPT = (
    "You are testing the tool `{name}`, which is a {kind}. Invent a realistic fake use case "
    "for it, then call the tool once with plausible sample arguments for that use case."
)

FAILURE_TEMPLATE = """Tool: {tool_name}
Input: {input}
Output received: {output}
Error: {error}

The following is the error. Check the tool definition, the input calling format, debug, and \
verify from the tool endpoint details."""

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}
_WRITE_WORDS = ("place", "create", "add", "update", "delete", "cancel", "submit", "post", "send")


@dataclass
class ToolDetails:
    fn: typing.Callable
    spec: dict
    kind: str


# (service, tool) -> (sha256 of the source, details). A patched source has a new hash, so the
# next tool_details call recompiles it; an unchanged source reuses the compiled function.
_DETAILS: dict[tuple[str, str], tuple[str, ToolDetails]] = {}


def _trim(text) -> str:
    text = str(text)
    return text if len(text) <= MAX_DETAIL else text[: MAX_DETAIL - 3] + "..."


def _redact(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


def _load_tool(source: str, tool_name: str):
    """Compile `source` in a fresh in-memory module and return its tool function."""
    module = types.ModuleType(f"_verify_{tool_name}")
    exec(compile(source, f"<{tool_name}>", "exec"), module.__dict__)  # noqa: S102 - our own generated code
    for name, fn in inspect.getmembers(module, inspect.iscoroutinefunction):
        if fn.__module__ == module.__name__ and not name.startswith("_") and not name.endswith("_request"):
            return fn
    raise ValueError("no tool function found in source")


def _arg_docs(doc: str) -> dict:
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\s{4}(\w+):\s*(.+)$", doc, re.MULTILINE)}


def _kind(name: str, description: str) -> str:
    text = f"{name} {description}".lower()
    return "write action" if any(w in text for w in _WRITE_WORDS) else "read-only lookup"


def tool_details(service_name: str, tool_name: str, *, cache: ToolCache) -> ToolDetails:
    """Read the tool source from the cache and build its function + Bedrock definition."""
    source = cache.get_source(service_name, tool_name)  # also validates both names
    if source is None:
        raise LookupError(f"no cached source for {service_name}/{tool_name}")
    digest = hashlib.sha256(source.encode()).hexdigest()
    cached = _DETAILS.get((service_name, tool_name))
    if cached and cached[0] == digest:
        return cached[1]

    fn = _load_tool(source, tool_name)
    doc = inspect.getdoc(fn) or ""
    docs = _arg_docs(doc)
    props, required = {}, []
    for name, p in inspect.signature(fn).parameters.items():
        if name == "token":  # injected at call time, never shown to the LLM
            continue
        ann = p.annotation
        if typing.get_origin(ann) or hasattr(ann, "__args__"):
            ann = next((a for a in ann.__args__ if a is not type(None)), str)
        props[name] = {"type": _JSON_TYPES.get(ann, "string"), "description": docs.get(name, name)}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    description = doc.split("\n\n")[0]
    spec = {
        "name": fn.__name__,
        "description": description + TEST_SUFFIX,
        "inputSchema": {"json": {"type": "object", "properties": props, "required": required}},
    }
    details = ToolDetails(fn=fn, spec=spec, kind=_kind(tool_name, description))
    _DETAILS[(service_name, tool_name)] = (digest, details)
    return details


async def call_tool_via_llm(
    details: ToolDetails, token: str, *, client=None, model_id=None, base_url: str | None = None,
) -> dict:
    """Let the LLM call the tool. Returns {"input", "output", "error"} (JSON-serialisable).

    `base_url` is the service URL the tool reads with get_current_base_url() (not baked in).
    """
    record = {"input": None, "output": None, "error": None}
    spec = details.spec
    try:
        reply = await asyncio.to_thread(
            bedrock_client(client).converse,
            modelId=model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
            messages=[{
                "role": "user",
                "content": [{"text": TEST_PROMPT.format(name=spec["name"], kind=details.kind)}],
            }],
            toolConfig={"tools": [{"toolSpec": spec}], "toolChoice": {"tool": {"name": spec["name"]}}},
        )
    except Exception as e:  # noqa: BLE001 - any LLM failure becomes a reportable error
        record["error"] = f"LLM call failed: {type(e).__name__}: {_trim(e)}"
        return record

    uses = [c["toolUse"] for c in reply["output"]["message"]["content"] if "toolUse" in c]
    if not uses:
        record["error"] = "the LLM did not call the tool"
        return record
    args = uses[0].get("input", {})
    record["input"] = args

    try:
        result = await call_with_token(details.fn, token, args, CALL_TIMEOUT, base_url=base_url)
    except TimeoutError:
        record["error"] = f"the endpoint did not respond within {CALL_TIMEOUT}s"
        return record
    except Exception as e:  # noqa: BLE001 - tool code is untrusted, report instead of raising
        record["error"] = f"request error: {type(e).__name__}: {_trim(e)}"
        return record
    try:
        record["output"] = json.loads(result)
    except (TypeError, ValueError):
        record["output"] = result
    return record


def parse_response(record: dict) -> str:
    """Classify a call record as RESPONSE_GENERATED or ERROR."""
    if record.get("error"):
        return ERROR
    output = record.get("output")
    if not output or not isinstance(output, (dict, list)):
        return ERROR
    if isinstance(output, dict) and set(output) == {"message", "status"}:
        return ERROR  # the generated tool's failure shape
    return RESPONSE_GENERATED


def build_failure_report(tool_name: str, record: dict, token: str | None = None) -> str:
    error = record.get("error")
    if not error and isinstance(record.get("output"), dict):
        out = record["output"]
        error = f"{out.get('message')} (HTTP status {out.get('status')})" if "message" in out else None
    report = FAILURE_TEMPLATE.format(
        tool_name=tool_name,
        input=json.dumps(record.get("input")),
        output=json.dumps(record.get("output"), default=str),
        error=error or "empty or non-JSON response",
    )
    return _redact(report, token)


async def hit_endpoint(
    service_name: str, tool_name: str, *, token: str | None = None,
    cache: ToolCache | None = None, client=None, model_id=None, service_uuid: str | None = None,
    version: str | None = None, error_storage=None, base_url: str | None = None,
):
    """Return "verified", or {"status": "failed", "detail": <last failure report>}."""
    token = token or get_dev_token(service_name)
    if not token:
        detail = f"no dev token stored for {dev_key(service_name)}"
        if service_uuid and version:
            await asyncio.to_thread(store_failure, service_uuid, version, tool_name, detail, None, error_storage)
        return {"status": "failed", "detail": detail}
    cache = cache or ToolCache.from_env()

    report = ""
    for _ in range(MAX_ATTEMPTS):
        try:
            details = tool_details(service_name, tool_name, cache=cache)
        except Exception as e:  # noqa: BLE001 - a broken tool is a failure to debug
            record = {"input": None, "output": None, "error": f"could not load tool: {type(e).__name__}: {_trim(e)}"}
        else:
            record = await call_tool_via_llm(
                details, token, client=client, model_id=model_id, base_url=base_url
            )
        if parse_response(record) == RESPONSE_GENERATED:
            return VERIFIED  # stored in mcptool storage by persist_verified under the same version
        report = build_failure_report(tool_name, record, token)
        try:
            await debug_using_llm(report, service_name, tool_name, cache=cache, client=client, model_id=model_id)
        except PatchInputError as e:
            report += f"\nPatch skipped: {e}"

    try:
        source = cache.get_source(service_name, tool_name)
        endpoint = cache.get_endpoint(service_name, tool_name)
    except Exception:  # noqa: BLE001 - the notification still goes out without the attachment
        source = endpoint = None
    if service_uuid and version:  # error storage first, same uuid/version/ layout as the bundle
        await asyncio.to_thread(store_failure, service_uuid, version, tool_name, report, source, error_storage)
    await notify_unresolved(
        service_name, tool_name, report, service_uuid=service_uuid, source=source, endpoint=endpoint
    )
    return {"status": "failed", "detail": report}

