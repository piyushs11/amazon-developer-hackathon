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

from backend.app.assistant import history

log = logging.getLogger(__name__)

MAX_TOOLS = 60
MAX_REPLY_CHARS = 300
JSON_TYPES = {"string", "integer", "number", "boolean"}

SYSTEM_PROMPT = """\
You are Alexa+, a voice assistant. The user asks for something that may need one of the tools \
below. Each tool belongs to a business service, named in [brackets].

How to decide:
1. If the request fits a tool, call that tool right away. Prefer calling a tool over asking a \
question. Pick the tool whose description matches what the user wants, and the service the user \
named (if they did not name one and only one service fits, use it).
2. Browsing, listing and searching ("what is on the menu", "show me the bouquets", "what do you \
have", "any pasta?") are tool calls: call the search or list tool. If the user gave no keyword, \
leave the query out; the tool then returns everything. Never ask the user for a keyword.
3. Use the conversation so far to understand short follow-ups ("order 2", "anything more in \
dessert?", "the same again", "my order"): fill the arguments from what was just discussed. Take \
argument values only from the conversation or the known values. Never invent ids, names, \
numbers or times. Only if a value the tool truly needs (an id, a time, a name to \
book under) is missing, do not call it; reply with one short question for that value.
4. The user can switch between services at any time. Go by what they ask for now, not by the \
service used before. If the request could fit tools of two different services equally well and \
they did not say which, do not guess: reply with one short question naming the services.
5. Never write what a service returned yourself (menus, dishes, prices, orders, availability, \
times), and never write "I found ...". Even if you remember an answer from earlier in the chat, \
call the tool again: only a tool call produces an answer.
6. If the request needs no tool (a greeting, thanks, something unrelated), reply in one short \
sentence and say what you can help with.
7. Never say an action was done. Actions only happen after a tool is called and the user confirms.

Output format: do not explain your reasoning and do not write <thinking> tags. Either call a tool, \
or reply in plain text under 25 words with no markdown and no tags."""

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


_THINK = re.compile(r"<thinking>.*?(</thinking>|\Z)", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"</?\s*(thinking|response|answer|reply)\s*>", re.IGNORECASE)
_RECORD = re.compile(r"\[(?:ran|showed|waiting)[^\]]*\]", re.IGNORECASE)  # copied from old history formats


def clean_text(text: str) -> str:
    """The model's reply without any reasoning it wrote out (<thinking>...</thinking>) or tags."""
    return " ".join(_RECORD.sub("", _TAGS.sub("", _THINK.sub("", text))).split())


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
            if tool.read_only and required == ["query"]:
                # a search: with no keyword it lists everything (the engine fills in the empty
                # query), so the model must not feel it has to ask for one
                required = []
                description += " Leave `query` out to list everything."
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


def _system(memory: dict | None, services=(), prefer=None) -> str:
    """The prompt, plus what the model should know: ids remembered from each service's own answers
    (kept per service so one service's id is never offered to another's tool), the service used
    last, and the summary of the earlier conversation."""
    known = []
    for svc in services:
        mine = ((memory or {}).get("ids") or {}).get(svc.uuid)
        for k, v in (mine.items() if isinstance(mine, dict) else []):
            if isinstance(v, (str, int)) and str(v):
                known.append(f"- [{svc.name}] {k} = {v}")
    out = SYSTEM_PROMPT
    if known:
        out += ("\n\nKnown values from earlier in this conversation (use one only for a tool of the "
                "service in [brackets], when the user says things like \"my order\"):\n" + "\n".join(known))
    if prefer is not None:
        out += (f"\n\nThe service used last was {prefer.name}. Prefer it only when the request fits "
                "several services equally well.")
    if history.context(memory):
        out += "\n\n" + history.context(memory)
    return out


def route(text: str, services: list, memory: dict | None = None, *, client=None,
          model=None, prefer=None) -> Routed:
    """Ask the model what to do with `text`. Raises on any LLM problem (the caller falls back)."""
    specs, index = build_tools(services)
    if not specs:
        raise LookupError("no tools to route to")
    model_name = model or model_id()
    extra = {}
    if "nova" in model_name:  # AWS advises greedy decoding for Nova tool use
        extra["additionalModelRequestFields"] = {"inferenceConfig": {"topK": 1}}
    reply = (client or get_client()).converse(
        modelId=model_name,
        system=[{"text": _system(memory, services, prefer)}],
        messages=history.messages(memory, text),
        toolConfig={"tools": specs, "toolChoice": {"auto": {}}},
        inferenceConfig={"maxTokens": 400, "temperature": 0},
        **extra,
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
    message = clean_text(" ".join(b["text"] for b in blocks if b.get("text")))
    if not message:
        raise ValueError("the model returned neither a tool call nor text")
    return Routed(message=message[:MAX_REPLY_CHARS])


SUMMARY_PROMPT = """\
You keep the memory of a conversation between a user and a voice assistant. You get the previous \
summary (maybe empty) and the next messages. Write the new summary: one plain-text paragraph \
under 100 words, no markdown, no tags, no reasoning. Keep what matters for later turns: what the \
user wants, which business or service is in use, dishes, items, quantities and ids mentioned, \
anything shown or offered, orders placed with their ids, and any question still open. Drop \
greetings and wording."""


def summarise(previous: str, old: list[dict], *, client=None, model=None) -> str:
    """Fold `old` messages into the running summary. Raises on any LLM problem (the caller then
    folds crudely, see history.record)."""
    lines = "\n".join(f"{'User' if m['role'] == 'user' else 'Alexa'}: {m['text']}"
                      + (f" ({m['note']})" if m.get("note") else "") for m in old)
    prompt = f"Previous summary: {previous or '(none)'}\n\nNew messages:\n{lines}"
    reply = (client or get_client()).converse(
        modelId=model or model_id(),
        system=[{"text": SUMMARY_PROMPT}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 250, "temperature": 0},
    )
    blocks = reply["output"]["message"]["content"]
    out = clean_text(" ".join(b["text"] for b in blocks if b.get("text")))
    if not out:
        raise ValueError("the model returned an empty summary")
    return out
