"""LLM router for Ask mode (ASSISTANT=llm): Bedrock picks the tool and fills in its arguments.

It replaces only the matching step of engine.py (`match` + `extract`). Everything after it is
unchanged and still decided by code, not by the model: is the service usable for this user,
write tools ask for a yes first (the business's confirmation prompt), the tool runs through the
gateway with the user's own token, and the answer is the business's template. The model never
sees tool results, so it cannot make up what a service said or claim an action was done.

Any problem here (no AWS access, throttling, a malformed reply) raises, and the engine falls
back to the rule-based matcher for that turn.

    ASSISTANT=llm              turn it on (default: rules)
    ASSISTANT_MODEL_ID=...     model for this step (default: BEDROCK_MODEL_ID, then the verifier's)
"""
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

MAX_TOOLS = 60
MAX_REPLY_CHARS = 300
JSON_TYPES = {"string", "integer", "number", "boolean"}

SYSTEM_PROMPT = """\
You are Alexa+, a voice assistant. The user asks for something that may need one of the tools \
below. Each tool belongs to a business service, named in [brackets].

- If the request fits a tool, call exactly one tool. Take the arguments from what the user said \
or from the known values; never invent ids, names, numbers or times.
- If a required value is missing and is not a known value, do not call a tool: reply with one \
short question asking for it.
- If the request needs no tool (a greeting, thanks, something unrelated), reply in one short \
sentence and say what you can help with.
- Never say that an action was done. Actions only happen after you call a tool and the user \
confirms.
- Replies are plain text, under 25 words, with no markdown."""


@dataclass
class Routed:
    """The model's decision: a tool call (service, tool, args) or a plain reply (message)."""
    service: object | None = None  # engine.ServiceInfo
    tool: object | None = None  # engine.ToolInfo
    args: dict = field(default_factory=dict)
    message: str = ""


_client = None  # tests replace this; production builds it on first use


def enabled() -> bool:
    return os.environ.get("ASSISTANT", "rules").strip().lower() == "llm"


def model_id() -> str:
    from backend.app.codegen.verifier.utilities import DEFAULT_MODEL_ID

    return (os.environ.get("ASSISTANT_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID")
            or DEFAULT_MODEL_ID)


def get_client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        _client = boto3.client(
            "bedrock-runtime",
            config=Config(connect_timeout=5, read_timeout=25, retries={"max_attempts": 2}),
        )
    return _client


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "service"


def _param_schema(tool, param: dict) -> dict:
    json_type = param.get("json_type") or "string"
    desc = (param.get("description") or param["name"]).strip()
    example = (tool.profile.get("example_args") or {}).get(param["name"])
    if example not in (None, ""):
        desc += f" (e.g. {example})"
    return {"type": json_type if json_type in JSON_TYPES else "string", "description": desc}


def build_tools(services: list) -> tuple[list[dict], dict[str, tuple]]:
    """(Bedrock toolSpecs, tool name -> (service, tool)). Names are unique across services."""
    specs, index = [], {}
    for service in services:
        slug = _slug(service.name)
        for tool in service.tools:
            if len(specs) >= MAX_TOOLS:
                break
            name = f"{slug}__{tool.name}"[:64]
            if name in index:  # two services with the same name and tool: keep them apart
                name = f"{name[:58]}_{len(specs)}"
            phrases = list((tool.profile.get("example_phrases") or [])[:3])
            description = f"[{service.name}] {tool.title}. {tool.description}".strip()
            if not tool.read_only:
                description += " (This changes something, so the user is asked to confirm.)"
            if phrases:
                description += " Example requests: " + " | ".join(f'"{p}"' for p in phrases)
            props = {p["name"]: _param_schema(tool, p) for p in tool.params}
            required = [p["name"] for p in tool.params if p["required"]]
            schema = {"type": "object", "properties": props}
            if required:
                schema["required"] = required
            specs.append({"toolSpec": {
                "name": name, "description": description[:1000], "inputSchema": {"json": schema},
            }})
            index[name] = (service, tool)
    return specs, index


def _coerce(value, json_type: str):
    """The value as the tool's type, or None when it does not fit."""
    try:
        if json_type == "integer":
            if isinstance(value, bool):
                return None
            return int(float(value))
        if json_type == "number":
            if isinstance(value, bool):
                return None
            return float(value)
        if json_type == "boolean":
            if isinstance(value, bool):
                return value
            return {"true": True, "false": False}.get(str(value).strip().lower())
        if value is None or isinstance(value, (dict, list)):
            return None
        return str(value).strip()
    except (TypeError, ValueError):
        return None


def clean_args(tool, raw: dict | None) -> dict:
    """Only the tool's own parameters, as the right types; anything else the model sent is dropped,
    and so are empty values (the engine then treats a required one as missing)."""
    out = {}
    for p in tool.params:
        if p["name"] not in (raw or {}):
            continue
        value = _coerce(raw[p["name"]], p.get("json_type") or "string")
        if value is not None and value != "":
            out[p["name"]] = value
    return out


def _system(memory: dict | None) -> str:
    known = {k: v for k, v in (memory or {}).items() if isinstance(v, (str, int)) and str(v)}
    if not known:
        return SYSTEM_PROMPT
    lines = "\n".join(f"- {k} = {v}" for k, v in known.items())
    return (SYSTEM_PROMPT + "\n\nKnown values from earlier in this conversation (use them when "
            "the user says things like \"my order\"):\n" + lines)


def route(text: str, services: list, memory: dict | None = None, *, client=None,
          model=None) -> Routed:
    """Ask the model what to do with `text`. Raises on any LLM problem (the caller falls back)."""
    specs, index = build_tools(services)
    if not specs:
        raise LookupError("no tools to route to")
    reply = (client or get_client()).converse(
        modelId=model or model_id(),
        system=[{"text": _system(memory)}],
        messages=[{"role": "user", "content": [{"text": text}]}],
        toolConfig={"tools": specs, "toolChoice": {"auto": {}}},
        inferenceConfig={"maxTokens": 400, "temperature": 0},
    )
    blocks = reply["output"]["message"]["content"]
    for block in blocks:
        use = block.get("toolUse")
        if not use:
            continue
        picked = index.get(use.get("name"))
        if picked is None:
            raise LookupError(f"the model called an unknown tool: {use.get('name')!r}")
        service, tool = picked
        log.info("assistant llm routed %r -> %s/%s", text[:60], service.name, tool.name)
        return Routed(service, tool, clean_args(tool, use.get("input")))
    message = " ".join(b["text"].strip() for b in blocks if b.get("text")).strip()
    if not message:
        raise ValueError("the model returned neither a tool call nor text")
    return Routed(message=message[:MAX_REPLY_CHARS])
