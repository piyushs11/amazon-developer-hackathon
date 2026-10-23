"""Rule-based Ask mode over every service in the catalog, driven only by database data.

    text -> score every (service, tool) against the tool's example phrases, title and name,
            plus the service's name -> best tool
         -> is the service usable for this user? (connected, published, switched on)
         -> arguments: ids by the shape of the example values (A1042, slot_0914), numbers,
            times, names from the service's own list tool (the menu, the bouquets), the user's
            remaining keywords, "for <name>" / "to <name>"
         -> write tool? ask first, with the business's confirmation prompt
         -> call the tool through the gateway (the user's own upstream token)
         -> answer with the business's speakable/empty/error templates

With ASSISTANT=llm, an LLM (llm.py, Bedrock) replaces `match` and `extract`: it picks the tool and
fills in the arguments. Access checks, the confirmation for writes, the gateway call and the
templates stay exactly as above, and any LLM failure falls back to the rules for that turn.
"""
import logging
import re
from dataclasses import dataclass, field

from backend.app.assistant import llm
from backend.app.assistant.speech import first_list, list_names, render, speak

log = logging.getLogger(__name__)

STOPWORDS = frozenset({
    "a", "an", "the", "at", "to", "of", "for", "from", "in", "on", "with", "and", "or", "is", "are",
    "was", "be", "do", "does", "did", "can", "could", "would", "will", "should", "i", "me", "my",
    "mine", "you", "your", "we", "our", "it", "its", "this", "that", "these", "those", "what",
    "whats", "what's", "which", "who", "whom", "how", "when", "where", "why", "there", "here",
    "please", "show", "tell", "give", "get", "find", "list", "any", "some", "have", "has", "had",
    "want", "like", "need", "about", "up", "just", "now", "today", "tonight", "it's", "i'd", "i'm",
    "let's", "ok", "okay", "hey", "hi", "hello", "alexa", "ask", "also", "again",
})
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "dozen": 12, "couple": 2}
YES = re.compile(r"^\s*(y|yes|yeah|yep|sure|ok|okay|go ahead|confirm|do it|please do)\b", re.IGNORECASE)
NO = re.compile(r"^\s*(n|no|nope|cancel|stop|don't|do not|never mind)\b", re.IGNORECASE)
TIME = re.compile(r"\b(\d{1,2}(?::\d{2})?\s?(?:am|pm))\b", re.IGNORECASE)
MIN_SCORE = 1.5


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_']+", text.lower().replace("&", " and "))


def content_words(text: str) -> set[str]:
    return {w.strip("'") for w in words(text) if w not in STOPWORDS and len(w) > 1}


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


@dataclass
class ToolInfo:
    name: str
    title: str
    description: str
    read_only: bool
    params: list[dict]  # MappedParam dicts: name, json_type, required, location, description
    profile: dict = field(default_factory=dict)


@dataclass
class ServiceInfo:
    uuid: str
    name: str
    profile: dict
    tools: list[ToolInfo]


def load_services() -> list[ServiceInfo]:
    """Every listed catalog service with its tools (registry, or the fixtures without Postgres)."""
    from backend.app.auth.settings import get_settings

    out = []
    if get_settings().registry == "postgres":
        from backend.app.db import registry

        for row in registry.list_services():
            tools_profile = (row.profile or {}).get("tools", {})
            tools = [ToolInfo(e.tool_name, tools_profile.get(e.endpoint_id, {}).get("title", e.tool_name),
                              e.description, e.read_only, [p.model_dump() for p in e.params],
                              tools_profile.get(e.endpoint_id) or tools_profile.get(e.tool_name) or {})
                     for e in registry.get_endpoints(row.service_uuid)]
            out.append(ServiceInfo(row.service_uuid, row.service_name, row.profile or {}, tools))
        return out
    from backend.app.api.catalog import _fixture

    for uuid, spec in _fixture("spec").items():
        if not spec.get("profile"):
            continue
        tools_profile = spec["profile"].get("tools", {})
        mapped = _fixture("mapped").get(uuid, {}).get("endpoints", [])
        tools = [ToolInfo(e["tool_name"], tools_profile.get(e["endpoint_id"], {}).get("title", e["tool_name"]),
                          e["description"], e["read_only"], e["params"], tools_profile.get(e["endpoint_id"], {}))
                 for e in mapped]
        out.append(ServiceInfo(uuid, spec["service_name"], spec["profile"], tools))
    return out


# ---- matching ----

def score(text: str, service: ServiceInfo, tool: ToolInfo, memory: dict | None = None) -> float:
    """How well `text` fits this tool:
      + distinct words shared with the tool's phrases, title and name (the main signal)
      + how completely one phrase is covered (a tie-breaker, halved)
      + the sentence starts like one of its phrases ("order ...", "where is ...", "book ...")
      + an id of the right shape is in the sentence ("A1042" -> get_order_status)
      - the tool needs an id that is neither in the sentence nor in the conversation
      + the service is named ("... at Lakeside Dental")
    """
    said = {_stem(w) for w in content_words(text)}
    if not said:
        return 0.0
    name_words = {_stem(w) for w in content_words(service.name)}
    named = bool(name_words) and name_words <= said
    said_task = said - name_words
    phrases = list(tool.profile.get("example_phrases") or []) + [tool.title, tool.name.replace("_", " ")]
    vocab, coverage, first_word = set(), 0.0, 0.0
    opening = (words(text) or [""])[0]
    for phrase in phrases:
        target = {_stem(w) for w in content_words(phrase)} - name_words
        if not target:
            continue
        vocab |= target
        coverage = max(coverage, len(said_task & target) / len(target))
        if (words(phrase) or [""])[0] == opening:
            first_word = 0.75
    total = len(said_task & vocab) + 0.5 * coverage + first_word
    for p in tool.params:
        example = (tool.profile.get("example_args") or {}).get(p["name"])
        regex = _id_regex(example) if isinstance(example, str) else None
        if not regex:
            continue
        if re.search(regex, text):
            total += 1.5
        elif p["required"] and p["name"] not in (memory or {}):
            total -= 1.0
    return total + (2.0 if named else 0.0)


def match(text: str, services: list[ServiceInfo], memory: dict | None = None
          ) -> tuple[ServiceInfo, ToolInfo, float] | None:
    ranked = sorted(((score(text, s, t, memory), i, s, t) for i, s in enumerate(services) for t in s.tools),
                    key=lambda x: (-x[0], x[1]))
    if not ranked or ranked[0][0] < MIN_SCORE:
        return None
    best, _, service, tool = ranked[0]
    return service, tool, best


# ---- arguments ----

def _id_regex(example: str) -> str | None:
    """'A1042' -> [A-Za-z]\\d{3,}; 'slot_0914' -> slot_\\d+; 'FC-0207' -> FC-\\d+; 'BK208' -> BK\\d+;
    '43215' -> five digits. None if not id-like."""
    m = re.fullmatch(r"([A-Za-z]+[_-])(\d+)", example)
    if m:
        return r"\b" + re.escape(m.group(1)) + r"\d+\b"
    if re.fullmatch(r"\d{4,}", example):  # zip codes, product numbers
        return r"\b\d{" + str(len(example)) + r"}\b"
    m = re.fullmatch(r"([A-Z]{1,3})(\d{2,})", example)
    if m:
        letters = r"[A-Za-z]" if len(m.group(1)) == 1 else re.escape(m.group(1))
        return r"\b" + letters + r"\d{2,}\b"
    return None


def _number(text: str) -> int | None:
    """"2 tiramisu", "two", "a dozen", "a pizza" (1). Times and ids are not numbers here."""
    text = re.sub(r"\b[A-Za-z]+_?\d+\b", " ", TIME.sub(" ", text))
    for w in words(text):
        if w.isdigit() and len(w) <= 3:
            return int(w)
        if w in NUMBER_WORDS and w not in ("a", "an"):
            return NUMBER_WORDS[w]
    return 1 if re.search(r"\b(a|an)\s+(?!table\b)", text.lower()) else None


def _is_list_tool(tool: ToolInfo) -> bool:
    """A read tool we can call with no real input: all params optional, or just a search query."""
    required = [p["name"] for p in tool.params if p["required"]]
    return tool.read_only and required in ([], ["query"])


def _list_values(service: ServiceInfo, call) -> list[str]:
    """Names offered by the service's list tools (the menu, the bouquets, the products), to
    recognise "tiramisu". All of them: a service can have several (search + view cart), and the
    stored tool order isn't meaningful."""
    names: list[str] = []
    for tool in service.tools:
        if _is_list_tool(tool):
            args = {p["name"]: "" for p in tool.params if p["required"]}
            res = call(service, tool, args)
            items = first_list(res.get("data")) if res else None
            for i in items or []:
                n = (i.get("name") or i.get("bouquet") or i.get("item")) if isinstance(i, dict) else None
                if isinstance(n, str) and n not in names:
                    names.append(n)
    return names


def _pick_name(text: str, names: list[str]) -> str | None:
    said = {_stem(w) for w in content_words(text)}
    best, best_hits = None, 0
    for name in names:
        target = {_stem(w) for w in content_words(name)}
        hits = len(said & target)
        if hits > best_hits or (hits == best_hits and hits and name.lower() in text.lower()):
            best, best_hits = name, hits
    return best


def extract(text: str, service: ServiceInfo, tool: ToolInfo, memory: dict, call) -> tuple[dict, list[dict]]:
    """(arguments, missing required params)."""
    args: dict = {}
    examples = tool.profile.get("example_args") or {}
    searched = False  # only one search-style field gets the user's keywords
    for p in tool.params:
        name, jtype = p["name"], p.get("json_type", "string")
        example = examples.get(name)
        if example is None:  # "Store id ..., e.g. FC-0207" in the description is an example too
            m = re.search(r"e\.g\.\s*([A-Za-z0-9][A-Za-z0-9_-]*)", p.get("description") or "")
            example = m.group(1) if m else None
        value = None
        regex = _id_regex(example) if isinstance(example, str) else None
        if regex:
            m = re.search(regex, text)
            if m:
                value = m.group(0)
            elif name in memory:
                value = memory[name]  # "where is my order" -> the order placed a moment ago
        elif jtype in ("integer", "number"):
            value = _number(text)
        elif name == "time" or (isinstance(example, str) and re.search(r"\d(:\d\d)?\s?(am|pm)", example, re.IGNORECASE)):
            m = TIME.search(text)
            value = m.group(1).upper().replace("AM", " AM").replace("PM", " PM").replace("  ", " ") if m else None
        elif re.search(r"recipient|person|name_of|for_whom", name):
            m = re.search(r"\b(?:to|for)\s+(?:my\s+)?([A-Za-z][A-Za-z'-]+)", text)
            value = m.group(1).title() if m and m.group(1).lower() not in STOPWORDS else None
        elif not tool.read_only:
            names = _list_values(service, call)
            value = _pick_name(text, names) if names else None
        elif not searched:
            # A search-style field: what's left after the service name and the tool's own words
            # ("does FreshCart have oat milk" -> "oat milk"). Later optional text fields stay empty.
            searched = True
            noise = content_words(service.name) | content_words(tool.title) | content_words(tool.name.replace("_", " "))
            noise |= {"menu", "have", "available", "options", "something", "anything", "bouquets", "dishes", "food",
                      "near", "nearest", "closest", "much", "cost", "price", "store", "stores", "location", "shop"}
            rest = [w for w in words(text) if w not in STOPWORDS and w not in noise and len(w) > 2
                    and not re.fullmatch(r"\d+", w)]
            value = " ".join(rest) if rest else ("" if p["required"] else None)
        if value is not None:
            args[name] = value
    missing = [p for p in tool.params if p["required"] and args.get(p["name"]) is None]
    return args, missing


# ---- the conversation step ----

def _items(data: dict | None) -> list[dict] | None:
    items = first_list(data)
    if not items or not all(isinstance(i, dict) for i in items):
        return None
    out = []
    for i in items[:6]:
        name = i.get("name") or i.get("label") or i.get("bouquet") or i.get("item")
        if not name:
            return None
        tags = i.get("tags") or i.get("occasions") or []
        out.append({"name": name, "detail": ", ".join(tags) if isinstance(tags, list) else str(tags),
                    "price": i.get("price")})
    return out


def _memory_from(data: dict | None) -> dict:
    return {k: v for k, v in (data or {}).items() if k.endswith("_id") and isinstance(v, str)}


def suggestions(live: list[ServiceInfo], memory: dict) -> list[str]:
    out = []
    for s in live:
        out += (s.profile.get("phrases") or [])[:2]
    if memory.get("order_id"):
        out.insert(0, "Where is order " + memory["order_id"])
    return out[:5]


@dataclass
class Access:
    status: str  # ok | not_connected | expired | not_published | off


def answer(*, text: str, pending: dict | None, memory: dict, services: list[ServiceInfo],
           access, call) -> dict:
    """One turn. `access(service) -> Access`; `call(service, tool, args) -> {text, data, is_error,
    status, ms}` runs the tool through the gateway as the user."""
    by_uuid = {s.uuid: s for s in services}
    live = [s for s in services if access(s).status == "ok"]
    memory = dict(memory or {})

    def reply(text_, kind="answer", **extra):
        return {"reply": text_, "kind": kind, "memory": memory, "pending": None,
                "suggestions": suggestions(live, memory), **extra}

    def run(service: ServiceInfo, tool: ToolInfo, args: dict) -> dict:
        res = call(service, tool, args)
        data = res.get("data") if isinstance(res.get("data"), dict) else {}
        status = data.get("status") if isinstance(data.get("status"), int) else None
        spoken = speak(tool.profile, data, is_error=res["is_error"], status=status, fallback=res.get("text", ""))
        if not res["is_error"]:
            memory.update(_memory_from(data))
        extra = {"items": _items(data)} if not res["is_error"] else {}
        return reply(spoken, "answer", call={
            "service_uuid": service.uuid, "service_name": service.name, "tool": tool.name, "arguments": args,
            "is_error": res["is_error"], "status": status, "ms": res.get("ms"), "data": data}, **extra)

    if pending:
        service = by_uuid.get(pending.get("service_uuid"))
        tool = next((t for t in (service.tools if service else []) if t.name == pending.get("tool")), None)
        if service and tool and YES.match(text):
            return run(service, tool, pending.get("arguments") or {})
        if NO.match(text) or not (service and tool):
            return reply("Okay, I won't do that.", "none")
        # Anything else: drop the pending action and treat this as a new request.

    if re.match(r"^\s*(hi|hello|hey|good (morning|evening|afternoon))\b", text, re.IGNORECASE):
        names = list_names([s.name for s in live]) or "your services"
        return reply(f"Hi! I can help with {names}. Try one of these.", "none")

    found, llm_args = None, None
    if services and llm.enabled():
        try:
            routed = llm.route(text, services, memory)
        except Exception as e:  # noqa: BLE001 - any LLM problem: use the rule-based matcher this turn
            log.warning("assistant llm routing failed (%s: %s); using the rules", type(e).__name__, e)
        else:
            if routed.tool is None:  # small talk, or the model asks for a missing value
                return reply(routed.message, "none")
            found, llm_args = (routed.service, routed.tool, 0.0), routed.args
    if found is None:
        found = match(text, services, memory)
    if found is None:
        if not live:
            return reply("You don't have any services on Alexa+ yet. Connect and publish one in MCP Bridge.",
                         "none", link=True)
        return reply(f"I didn't catch that. I can help with {list_names([s.name for s in live])}: "
                     f"try \"{suggestions(live, memory)[0]}\".", "none")
    service, tool, _ = found
    state = access(service).status
    blocked = {
        "not_connected": f"Please connect {service.name} in MCP Bridge first.",
        "expired": f"Your {service.name} sign-in expired. Please reconnect it in MCP Bridge.",
        "not_published": f"{service.name} isn't published yet. Publish it in MCP Bridge, then ask again.",
        "off": f"{service.name} is switched off. Turn it on in MCP Bridge to use it.",
    }.get(state)
    if blocked:
        return reply(blocked, "blocked", link=True, service_uuid=service.uuid)

    if llm_args is not None:
        args = dict(llm_args)
        for p in tool.params:
            if p["name"] in args or not p["required"]:
                continue
            if p["name"] in memory:  # "where is my order" -> the order placed a moment ago
                args[p["name"]] = memory[p["name"]]
            elif _is_list_tool(tool):  # "show me the menu": a search with no keywords
                args[p["name"]] = ""
        missing = [p for p in tool.params if p["required"] and args.get(p["name"]) is None]
    else:
        args, missing = extract(text, service, tool, memory, call)
    if missing:
        p = missing[0]
        example = (tool.profile.get("example_phrases") or [""])[0]
        hint = f" For example: \"{example}\"." if example else ""
        return reply(f"Which {p.get('description') or p['name'].replace('_', ' ')}?{hint}", "clarify")
    needs_ok = not tool.read_only or tool.profile.get("requires_confirmation")
    if needs_ok:
        prompt = render(tool.profile.get("confirmation_prompt"), args) or f"Should I run {tool.title} with {service.name}?"
        out = reply(prompt, "confirm")
        out["pending"] = {"service_uuid": service.uuid, "tool": tool.name, "arguments": args}
        return out
    return run(service, tool, args)
