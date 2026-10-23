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

One conversation can use several services. Every turn is routed by what the user says, not by
the service used last (that one only breaks an exact tie); each tool runs against its own service
through the gateway with the user's own token; ids remembered from answers are kept per service
(`memory["ids"][service_uuid]`) so one service's order_id is never offered to another's tool; a
pending yes/no belongs to its service and is dropped when the user changes topic.

With ASSISTANT=llm, an LLM (llm.py, Bedrock) replaces `match` and `extract`: it picks the tool and
fills in the arguments. Access checks, the confirmation for writes, the gateway call and the
templates stay exactly as above, and any LLM failure falls back to the rules for that turn.
"""
import json
import logging
import re
from dataclasses import dataclass, field

from backend.app.assistant import history, llm
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
# A reply to "Should I ...?" is only a yes/no when that is the whole message: "okay book a dentist
# appointment" or "cancel my dental appointment" are new requests, not answers.
YES = re.compile(r"(y|yes|yeah|yep|sure|ok|okay|go ahead|confirm|do it|please do|sounds good)"
                 r"( (please|thanks|thank you|do it|go ahead|that|it|confirm))*")
NO = re.compile(r"(n|no|nope|cancel|stop|don't|do not|never mind|nevermind)"
                r"( (thanks|thank you|please|that|it|do it|cancel|stop))*")
IDS_KEY = "ids"  # memory: {service_uuid: {order_id: "A2001"}}
LAST_KEY = "_last_service"  # memory: uuid of the service used last (only a tie-breaker)
CHOOSE_KEY = "_choose"  # memory: {"text": the request, "uuids": the services we asked about}
AMBIGUOUS_MARGIN = 1.0  # "Lakeside": services whose best tool scores within this are all possible
TIE = 0.05  # otherwise two services must score (almost) exactly the same to be ambiguous
TIME = re.compile(r"\b(\d{1,2}(?::\d{2})?\s?(?:am|pm))\b", re.IGNORECASE)
MIN_SCORE = 1.5


def is_yes(text: str) -> bool:
    return bool(YES.fullmatch(" ".join(words(text))))


def is_no(text: str) -> bool:
    return bool(NO.fullmatch(" ".join(words(text))))


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


def _rank(text: str, services: list[ServiceInfo], memory: dict | None = None
          ) -> list[tuple[float, int, ServiceInfo, ToolInfo]]:
    return sorted(((score(text, s, t, ids_for(memory, s)), i, s, t) for i, s in enumerate(services) for t in s.tools),
                  key=lambda r: (-r[0], r[1]))


def match(text: str, services: list[ServiceInfo], memory: dict | None = None
          ) -> tuple[ServiceInfo, ToolInfo, float] | None:
    """The best (service, tool) for `text`, or None when nothing fits. See `pick` for the version
    that notices ambiguity between services."""
    ranked = _rank(text, services, memory)
    if not ranked or ranked[0][0] < MIN_SCORE:
        return None
    best, _, service, tool = ranked[0]
    return service, tool, best


@dataclass
class Pick:
    found: tuple[ServiceInfo, ToolInfo, float] | None = None
    ask: list[ServiceInfo] = field(default_factory=list)  # services to ask the user to choose from
    shared: bool = False  # the ambiguity is a shared name word ("Lakeside"), not a tie of scores


def _name_stems(service: ServiceInfo) -> set[str]:
    return {_stem(w) for w in content_words(service.name)}


def pick(text: str, services: list[ServiceInfo], memory: dict | None = None, prefer: str | None = None) -> Pick:
    """Which service and tool the user means, by what they said.

    The service used last (`prefer`, a uuid) never overrides the words: it only settles a tie
    between services that fit equally well. If it cannot, the user is asked which service.
      - "Lakeside" shares a word with two service names and names neither in full: the services
        whose best tool is within AMBIGUOUS_MARGIN of the top are all possible.
      - otherwise services must score exactly alike to be ambiguous.
    """
    said = {_stem(w) for w in content_words(text)}
    best: dict[str, tuple[float, int, ServiceInfo, ToolInfo]] = {}
    for r in _rank(text, services, memory):
        best.setdefault(r[2].uuid, r)
    per = list(best.values())  # best tool of each service, best first
    if not per:
        return Pick()
    group = [s for s in services if _name_stems(s) & said]
    shared = len(group) >= 2 and not any(_name_stems(s) <= said for s in group)
    if shared:
        per = [r for r in per if r[2].uuid in {s.uuid for s in group}]
    top = per[0][0]
    if not shared and top < MIN_SCORE:
        return Pick()
    tied = [r for r in per if top - r[0] <= (AMBIGUOUS_MARGIN if shared else TIE)]
    if len(tied) > 1:
        preferred = next((r for r in tied if r[2].uuid == prefer), None)
        if preferred and top >= MIN_SCORE:
            return Pick(found=(preferred[2], preferred[3], preferred[0]))
        return Pick(ask=[r[2] for r in tied], shared=shared)
    if top < MIN_SCORE:
        return Pick()
    return Pick(found=(per[0][2], per[0][3], top))


def _picked_service(text: str, cands: list[ServiceInfo]) -> ServiceInfo | None:
    """The one of `cands` the user's answer to "Do you mean A or B?" names, by the words that tell
    them apart ("the dental one" -> Lakeside Dental). None if it names none, or several."""
    said = {_stem(w) for w in content_words(text)}
    common = set.intersection(*(_name_stems(s) for s in cands)) if cands else set()
    hits = [s for s in cands if (_name_stems(s) - common or _name_stems(s)) <= said]
    return hits[0] if len(hits) == 1 else None


# ---- ids remembered per service ----

def ids_for(memory: dict | None, service: ServiceInfo) -> dict:
    """Ids remembered from this service's own answers: {"order_id": "A2001"}."""
    mine = ((memory or {}).get(IDS_KEY) or {}).get(service.uuid)
    return {k: v for k, v in mine.items() if isinstance(v, str)} if isinstance(mine, dict) else {}


def _clean_ids(raw) -> dict:
    """The client sends memory back, so trust only its shape: {uuid: {name: str}}, small."""
    if not isinstance(raw, dict):
        return {}
    return {u: {k: v for k, v in list(ids.items())[:20] if isinstance(k, str) and isinstance(v, str)}
            for u, ids in list(raw.items())[:20] if isinstance(u, str) and isinstance(ids, dict)}


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
        if ids_for(memory, s).get("order_id"):
            out.insert(0, "Where is order " + ids_for(memory, s)["order_id"])
    return out[:5]


@dataclass
class Access:
    status: str  # ok | not_connected | expired | not_published | off


def _note(kind: str, extra: dict) -> str:
    """What the model should know about a turn beyond the words Alexa said: the tool that ran, the
    items shown (so "the first one" works), or that a yes/no is awaited."""
    parts = []
    call_info = extra.get("call")
    if call_info:
        args = json.dumps(call_info.get("arguments") or {}, ensure_ascii=False)
        parts.append(f"[ran {call_info.get('service_name', '')}/{call_info['tool']} {args}]")
    items = extra.get("items") or []
    if items:
        shown = ", ".join(i["name"] + (f" ({i['price']})" if i.get("price") is not None else "") for i in items[:8])
        parts.append(f"[showed: {shown}]")
    if kind == "confirm":
        parts.append("[waiting for the user to say yes or no]")
    return " ".join(parts)


def _blocked_message(service: ServiceInfo, state: str) -> str | None:
    return {
        "not_connected": f"Please connect {service.name} in MCP Bridge first.",
        "expired": f"Your {service.name} sign-in expired. Please reconnect it in MCP Bridge.",
        "not_published": f"{service.name} isn't published yet. Publish it in MCP Bridge, then ask again.",
        "off": f"{service.name} is switched off. Turn it on in MCP Bridge to use it.",
    }.get(state)


def _either(names: list[str]) -> str:
    return ", ".join(names[:-1]) + " or " + names[-1] if len(names) > 1 else "".join(names)


def answer(*, text: str, pending: dict | None, memory: dict, services: list[ServiceInfo],
           access, call) -> dict:
    """One turn. `access(service) -> Access`; `call(service, tool, args) -> {text, data, is_error,
    status, ms}` runs the tool through the gateway as the user."""
    by_uuid = {s.uuid: s for s in services}
    live = [s for s in services if access(s).status == "ok"]
    memory = dict(memory or {})
    memory[IDS_KEY] = _clean_ids(memory.get(IDS_KEY))
    last = memory.get(LAST_KEY) if isinstance(memory.get(LAST_KEY), str) else None
    choose = memory.pop(CHOOSE_KEY, None)  # an open "Do you mean A or B?" lasts one turn
    request, scope = text, services  # what to route, and among which services

    def reply(text_, kind="answer", service=None, tool=None, **extra):
        if service is not None:
            # With several services in play, say which one answered.
            if kind != "blocked" and len(live) > 1 and service.name.lower() not in text_.lower():
                text_ = f"{service.name}: {text_}"
            extra["via"] = {"service": service.name, "tool": tool.name if tool else None,
                            "switched": bool(last) and last != service.uuid}
            extra["service"] = {"uuid": service.uuid, "name": service.name}
            if kind != "blocked":
                memory[LAST_KEY] = service.uuid
        if llm.enabled():  # the router needs the conversation so far (history.py)
            history.record(memory, user=text, alexa=text_, note=_note(kind, extra),
                           summarise=llm.summarise)
        return {"reply": text_, "kind": kind, "memory": memory, "pending": None,
                "suggestions": suggestions(live, memory), **extra}

    def run(service: ServiceInfo, tool: ToolInfo, args: dict) -> dict:
        res = call(service, tool, args)
        data = res.get("data") if isinstance(res.get("data"), dict) else {}
        status = data.get("status") if isinstance(data.get("status"), int) else None
        spoken = speak(tool.profile, data, is_error=res["is_error"], status=status, fallback=res.get("text", ""))
        if not res["is_error"] and _memory_from(data):
            memory[IDS_KEY].setdefault(service.uuid, {}).update(_memory_from(data))
        extra = {"items": _items(data)} if not res["is_error"] else {}
        return reply(spoken, "answer", service=service, tool=tool, call={
            "service_uuid": service.uuid, "service_name": service.name, "tool": tool.name, "arguments": args,
            "is_error": res["is_error"], "status": status, "ms": res.get("ms"), "data": data}, **extra)

    def blocked(service: ServiceInfo, state: str) -> dict | None:
        msg = _blocked_message(service, state)
        if msg is None:
            return None
        return reply(msg, "blocked", service=service, link=True, service_uuid=service.uuid)

    def ask_which(options: list[ServiceInfo]) -> dict:
        memory[CHOOSE_KEY] = {"text": request, "uuids": [s.uuid for s in options]}
        return reply(f"Do you mean {_either([s.name for s in options])}?", "clarify")

    if pending:
        service = by_uuid.get(pending.get("service_uuid"))
        tool = next((t for t in (service.tools if service else []) if t.name == pending.get("tool")), None)
        if service and tool and is_yes(text):
            # Things may have changed since it was asked (disconnected, switched off).
            return blocked(service, access(service).status) or run(service, tool, pending.get("arguments") or {})
        if is_no(text) or not (service and tool):
            return reply("Okay, I won't do that.", "none")
        # Anything else: the user moved on. Drop the pending action and route this as a new request.
    elif isinstance(choose, dict):
        options = [by_uuid[u] for u in choose.get("uuids") or [] if u in by_uuid]
        chosen = _picked_service(text, options) if isinstance(choose.get("text"), str) else None
        if chosen:  # "the dental one": run the request we asked about, on that service only
            request, scope = choose["text"], [chosen]
            if not match(request, scope, memory):
                memory[LAST_KEY] = chosen.uuid
                return reply(f"Okay, {chosen.name}. What would you like to do?", "clarify", service=chosen)

    if re.match(r"^\s*(hi|hello|hey|good (morning|evening|afternoon))\b", text, re.IGNORECASE):
        names = list_names([s.name for s in live]) or "your services"
        return reply(f"Hi! I can help with {names}. Try one of these.", "none")

    # Rules first: they spot "Lakeside" (two services share the word) and, without an LLM, ties.
    chosen_by_rules = pick(request, scope, memory, prefer=last)
    if chosen_by_rules.ask and (chosen_by_rules.shared or not llm.enabled()):
        return ask_which(chosen_by_rules.ask)
    found, llm_args = None, None
    if scope and llm.enabled():
        try:
            routed = llm.route(request, scope, memory, prefer=by_uuid.get(last))
        except Exception as e:  # noqa: BLE001 - any LLM problem: use the rule-based matcher this turn
            log.warning("assistant llm routing failed (%s: %s); using the rules", type(e).__name__, e)
        else:
            if routed.tool is None:  # small talk, a question for the user, or a missing value
                return reply(routed.message, "none")
            found, llm_args = (routed.service, routed.tool, 0.0), routed.args
    if found is None:
        if chosen_by_rules.ask:  # the LLM failed on an ambiguous request
            return ask_which(chosen_by_rules.ask)
        found = chosen_by_rules.found
    if found is None:
        if not live:
            return reply("You don't have any services on Alexa+ yet. Connect and publish one in MCP Bridge.",
                         "none", link=True)
        return reply(f"I didn't catch that. I can help with {list_names([s.name for s in live])}: "
                     f"try \"{suggestions(live, memory)[0]}\".", "none")
    service, tool, _ = found
    # A service that isn't usable gets its own message; we never fall back to another service.
    if hit := blocked(service, access(service).status):
        return hit

    mine = ids_for(memory, service)  # only ids this service gave us
    if llm_args is not None:
        args = dict(llm_args)
        for p in tool.params:
            if p["name"] in args or not p["required"]:
                continue
            if p["name"] in mine:  # "where is my order" -> the order placed a moment ago
                args[p["name"]] = mine[p["name"]]
            elif _is_list_tool(tool):  # "show me the menu": a search with no keywords
                args[p["name"]] = ""
        missing = [p for p in tool.params if p["required"] and args.get(p["name"]) is None]
    else:
        args, missing = extract(request, service, tool, mine, call)
    if missing:
        p = missing[0]
        example = (tool.profile.get("example_phrases") or [""])[0]
        hint = f" For example: \"{example}\"." if example else ""
        return reply(f"Which {p.get('description') or p['name'].replace('_', ' ')}?{hint}", "clarify",
                     service=service, tool=tool)
    needs_ok = not tool.read_only or tool.profile.get("requires_confirmation")
    if needs_ok:
        prompt = render(tool.profile.get("confirmation_prompt"), args) or f"Should I run {tool.title} with {service.name}?"
        out = reply(prompt, "confirm", service=service, tool=tool)
        out["pending"] = {"service_uuid": service.uuid, "tool": tool.name, "arguments": args}
        return out
    return run(service, tool, args)
