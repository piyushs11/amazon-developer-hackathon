"""Debug and patch a generated tool that failed verification.

debug_using_llm asks Bedrock for a minimal fix (old/new snippets + the patched file),
then verify_changes checks the patch against its own list of changes and writes it to the
Redis tool cache. It returns the verified source, or None if the patch could not be verified.
"""

import asyncio
import json
import os

from backend.app.storage.tool_cache import ToolCache

from .utilities import DEFAULT_MODEL_ID, bedrock_client, verify_changes

ENDPOINT_JSON_GUIDE = """\
The endpoint JSON is one entry of a MappedService:
- tool_name / endpoint_id: the tool's name
- method: HTTP method (GET, POST, PUT, PATCH, DELETE)
- path_template: the URL path, with {name} placeholders filled from the "path" params;
  the base URL is NOT part of it
- params: list of {name, python_type, json_type, required, location, description};
  location is one of path (in the URL), query (query string), body (JSON body), header
- read_only: true only for GET
- input_schema: the JSON schema the model sees for the tool's arguments"""

PATCH_PROMPT = """\
A generated tool failed when it was tested against the service's endpoint.

## Why the call failed
{report}

## Tool source ({service_name}/{tool_name})
```python
{source}
```

## Endpoint details
{endpoint_guide}

```json
{endpoint}
```

## What to do
Use the failure report to understand why the tool call failed, compare the code with the \
endpoint details, and fix the tool.

Guidelines:
- Make the MINIMAL change that fixes the issue; do not touch unrelated code.
- Keep every function name and the JSON-string return format. The tool function takes NO \
`token` parameter: it reads the token with `get_current_token()` right before calling the \
`*_request` helper (which does take `token`). Do not add or remove either.
- Check the syntax and that the file compiles before you answer.
- Call `submit_patch` with the complete patched file and the exact list of changes. For each \
change give `old` (the exact text currently in the file, appearing exactly once), `new` \
(its replacement), `line` (the 1-based line number where `old` starts in the ORIGINAL file) \
and a short `reason`. The patched file must contain these changes and nothing else."""

PATCH_TOOL = {
    "name": "submit_patch",
    "description": "Submit the patched tool file and the exact changes made to it.",
    "inputSchema": {"json": {
        "type": "object",
        "properties": {
            "patched_source": {"type": "string", "description": "The complete patched file."},
            "changes": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "line": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["old", "new", "line", "reason"],
            }},
        },
        "required": ["patched_source", "changes"],
    }},
}


class PatchInputError(ValueError):
    """A required input for patching is missing."""


def _missing_inputs(report, service_name, tool_name, source, endpoint) -> list[str]:
    checks = {
        "report": report, "service_name": service_name, "tool_name": tool_name,
        "tool source": source, "endpoint JSON": endpoint,
    }
    return [label for label, value in checks.items() if not value]


async def debug_using_llm(
    report: str, service_name: str, tool_name: str, *,
    cache: ToolCache | None = None, client=None, model_id=None,
) -> str | None:
    """Return the verified patched source (already saved to the cache), or None."""
    cache = cache or ToolCache.from_env()
    source = endpoint = None
    if service_name and tool_name:
        source = cache.get_source(service_name, tool_name)
        endpoint = cache.get_endpoint(service_name, tool_name)
    missing = _missing_inputs(report, service_name, tool_name, source, endpoint)
    if missing:
        raise PatchInputError(f"missing: {', '.join(missing)}")

    prompt = PATCH_PROMPT.format(
        report=report, service_name=service_name, tool_name=tool_name, source=source,
        endpoint_guide=ENDPOINT_JSON_GUIDE, endpoint=json.dumps(endpoint, indent=2),
    )
    try:
        reply = await asyncio.to_thread(
            bedrock_client(client).converse,
            modelId=model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            toolConfig={"tools": [{"toolSpec": PATCH_TOOL}], "toolChoice": {"tool": {"name": "submit_patch"}}},
        )
        uses = [c["toolUse"] for c in reply["output"]["message"]["content"] if "toolUse" in c]
        patch = uses[0]["input"]
        changes, patched = patch["changes"], patch["patched_source"]
    except Exception:  # noqa: BLE001 - any LLM/parse failure means "not patched"
        return None

    result = verify_changes(service_name, tool_name, changes, patched, cache=cache)
    return result["source"] if result["status"] == "verified" else None
