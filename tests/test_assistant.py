"""Ask mode engine: tool matching, arguments, confirmation, blocked services, answers.

Uses the real catalog specs (their phrases and templates) and a fake `call` that answers like
the mock APIs, so no database or network is needed.
"""
import json
import re
from pathlib import Path

import pytest

from backend.app.assistant import engine
from backend.app.mapper import map_service
from backend.app.spec import parse_spec

SPECS = Path(__file__).resolve().parents[1] / "mock-services/catalog/specs"
MENU = [{"name": "Spaghetti Carbonara", "tags": ["pasta"]}, {"name": "Tiramisu", "tags": ["dessert"]},
        {"name": "Margherita Pizza", "tags": ["pizza"]}]


def _service(file: str) -> engine.ServiceInfo:
    raw = json.loads((SPECS / file).read_text(encoding="utf-8"))
    mapped = map_service(parse_spec(raw))
    tools_profile = raw["profile"]["tools"]
    return engine.ServiceInfo(raw["service_uuid"], raw["service_name"], raw["profile"], [
        engine.ToolInfo(e.tool_name, tools_profile[e.endpoint_id]["title"], e.description, e.read_only,
                        [p.model_dump() for p in e.params], tools_profile[e.endpoint_id]) for e in mapped.endpoints])


SERVICES = [_service("demo_bistro.json"), _service("lakeside_dental.json"), _service("lakeside_grill.json")]
BISTRO, DENTAL, GRILL = SERVICES


class FakeWorld:
    def __init__(self, live=("Demo Bistro",), states=None):
        self.calls = []
        self.live, self.states = set(live), states or {}

    def access(self, service):
        if service.name in self.states:
            return engine.Access(self.states[service.name])
        return engine.Access("ok" if service.name in self.live else "not_connected")

    def call(self, service, tool, args):
        self.calls.append((tool.name, args))
        if tool.name == "search_menu":
            q = args.get("query", "")
            return {"data": {"results": [m for m in MENU if not q or q in m["tags"] or q in m["name"].lower()]},
                    "is_error": False, "text": ""}
        if tool.name == "place_order":
            return {"data": {"order_id": "A2001", **args, "eta_minutes": 30}, "is_error": False, "text": ""}
        if tool.name == "get_order_status":
            if args["order_id"] == "Z999":
                return {"data": {"message": "not found", "status": 404}, "is_error": True, "text": "not found"}
            return {"data": {"order_id": args["order_id"], "status": "out for delivery", "eta_minutes": 10},
                    "is_error": False, "text": ""}
        if tool.name == "book_table":
            return {"data": {"booking_id": "BK300", **args}, "is_error": False, "text": ""}
        return {"data": {}, "is_error": False, "text": "ok"}

    def ask(self, text, pending=None, memory=None, services=None):
        return engine.answer(text=text, pending=pending, memory=memory or {}, services=services or SERVICES,
                             access=self.access, call=self.call)


@pytest.mark.parametrize("text, service, tool", [
    ("what pasta does Demo Bistro have", "Demo Bistro", "search_menu"),
    ("what is the status of order A1042", "Demo Bistro", "get_order_status"),
    ("order 2 tiramisu from Demo Bistro", "Demo Bistro", "place_order"),
    ("when is the next cleaning at Lakeside Dental", "Lakeside Dental", "next_available"),
    ("cancel my Lakeside Dental appointment apt_5521", "Lakeside Dental", "cancel_appointment"),
    ("book a table for 4 at 8 PM at Lakeside Grill", "Lakeside Grill", "book_table"),
    ("check booking BK208", "Lakeside Grill", "get_booking"),
])
def test_matches_the_right_tool(text, service, tool):
    s, t, _ = engine.match(text, SERVICES)
    assert (s.name, t.name) == (service, tool)


def test_read_tool_runs_and_answers_from_the_template():
    world = FakeWorld()
    out = world.ask("what pasta does Demo Bistro have")
    assert world.calls == [("search_menu", {"query": "pasta"})]
    assert out["kind"] == "answer" and out["reply"].startswith("I found 1 dishes at Demo Bistro")
    assert [i["name"] for i in out["items"]] == ["Spaghetti Carbonara"]


def test_write_tool_asks_first_then_runs_on_yes():
    world = FakeWorld()
    out = world.ask("order 2 tiramisu from Demo Bistro")
    assert out["kind"] == "confirm" and out["reply"] == "Should I order 2 × Tiramisu from Demo Bistro?"
    assert ("place_order", {"item": "Tiramisu", "quantity": 2}) not in world.calls  # not yet
    done = world.ask("yes", pending=out["pending"], memory=out["memory"])
    assert ("place_order", {"item": "Tiramisu", "quantity": 2}) in world.calls
    assert done["reply"].startswith("Done. Order A2001")
    # The new order id is remembered: "where is my order" uses it.
    follow = world.ask("where is my order", memory=done["memory"])
    assert world.calls[-1] == ("get_order_status", {"order_id": "A2001"})
    assert "out for delivery" in follow["reply"]


def test_no_cancels_the_pending_action():
    world = FakeWorld()
    out = world.ask("order a margherita pizza from Demo Bistro")
    assert out["pending"]["arguments"] == {"item": "Margherita Pizza", "quantity": 1}
    assert world.ask("no", pending=out["pending"])["reply"] == "Okay, I won't do that."
    assert not any(name == "place_order" for name, _ in world.calls)


def test_time_and_party_size_are_not_confused():
    world = FakeWorld(live=("Lakeside Grill",))
    out = world.ask("book a table at 7:30 pm for 4 at Lakeside Grill")
    assert out["pending"]["arguments"] == {"party_size": 4, "time": "7:30 PM"}


def test_error_answers_use_the_business_wording():
    out = FakeWorld().ask("what is the status of order Z999 at Demo Bistro")
    assert out["reply"] == "I couldn't find that order on your Demo Bistro account."
    assert out["call"]["is_error"] is True


@pytest.mark.parametrize("state, words", [
    ("not_connected", "connect Lakeside Dental"), ("expired", "reconnect"),
    ("not_published", "isn't published"), ("off", "switched off"),
])
def test_blocked_services_explain_why(state, words):
    out = FakeWorld(states={"Lakeside Dental": state}).ask("when is the next cleaning at Lakeside Dental")
    assert out["kind"] == "blocked" and words in out["reply"] and out["link"]


def test_missing_required_argument_asks_for_it():
    out = FakeWorld(live=("Lakeside Dental",)).ask("cancel my appointment at Lakeside Dental")
    assert out["kind"] == "clarify" and "Appointment id" in out["reply"]


def test_unknown_request_suggests_something():
    out = FakeWorld().ask("blah blah")
    assert out["kind"] == "none" and "Demo Bistro" in out["reply"] and out["suggestions"]


def _from_manifest(file: str) -> engine.ServiceInfo:
    from backend.app.submissions.manifest import manifest_to_spec

    manifest = json.loads((SPECS.parents[2] / "frontend/public/examples" / file).read_text(encoding="utf-8"))
    raw = manifest_to_spec(manifest, "fc")
    mapped = map_service(parse_spec(raw))
    tp = raw["profile"]["tools"]
    return engine.ServiceInfo("fc", raw["service_name"], raw["profile"], [
        engine.ToolInfo(e.tool_name, tp[e.endpoint_id]["title"], e.description, e.read_only,
                        [p.model_dump() for p in e.params], tp[e.endpoint_id]) for e in mapped.endpoints])


@pytest.mark.parametrize("text, tool, args", [
    ("does FreshCart have oat milk", "search_products", {"query": "oat milk"}),  # store_id stays empty
    ("does FreshCart have oat milk at store FC-0207", "search_products", {"query": "oat milk", "store_id": "FC-0207"}),
    ("find a FreshCart near 43215", "find_stores", {"zip": "43215"}),
    ("how much is FreshCart product FC1008", "get_product", {"product_id": "FC1008"}),
])
def test_manifest_service_arguments(text, tool, args):
    fresh = _from_manifest("freshcart-1.0.json")
    service, found, _ = engine.match(text, [fresh])
    assert found.name == tool
    got, missing = engine.extract(text, service, found, {}, lambda *_: {"data": {}})
    assert not missing and got == args


# ---- ASSISTANT=llm: Bedrock picks the tool, the rest of the engine is unchanged ----

class StubBedrock:
    """Answers like Converse: a scripted tool call or text; records what it was sent."""

    def __init__(self, tool=None, args=None, text="", fail=None):
        self.tool, self.args, self.text, self.fail = tool, args or {}, text, fail
        self.sent = []

    def converse(self, **kw):
        self.sent.append(kw)
        if self.fail:
            raise self.fail
        if self.tool:
            name = next(t["toolSpec"]["name"] for t in kw["toolConfig"]["tools"]
                        if t["toolSpec"]["name"].endswith("__" + self.tool))
            block = {"toolUse": {"toolUseId": "t1", "name": name, "input": self.args}}
        else:
            block = {"text": self.text}
        return {"output": {"message": {"role": "assistant", "content": [block]}}}


@pytest.fixture
def llm_on(monkeypatch):
    from backend.app.assistant import llm

    monkeypatch.setenv("ASSISTANT", "llm")

    def use(stub):
        monkeypatch.setattr(llm, "_client", stub)
        return stub

    return use


def test_llm_picks_the_tool_and_the_engine_still_asks_before_a_write(llm_on):
    stub = llm_on(StubBedrock("place_order", {"item": "Tiramisu", "quantity": "2", "junk": "x"}))
    world = FakeWorld()
    out = world.ask("get me a couple of tiramisus")
    assert out["kind"] == "confirm" and out["reply"] == "Should I order 2 × Tiramisu from Demo Bistro?"
    assert out["pending"]["arguments"] == {"item": "Tiramisu", "quantity": 2}  # typed, junk dropped
    assert world.calls == []  # nothing ran yet
    assert stub.sent[0]["toolConfig"]["toolChoice"] == {"auto": {}}
    done = world.ask("yes", pending=out["pending"], memory=out["memory"])
    assert ("place_order", {"item": "Tiramisu", "quantity": 2}) in world.calls
    assert done["reply"].startswith("Done. Order A2001")


def test_llm_read_tool_answers_with_the_business_template(llm_on):
    llm_on(StubBedrock("search_menu", {"query": "pasta"}))
    world = FakeWorld()
    out = world.ask("anything italian and carb-heavy?")
    assert world.calls == [("search_menu", {"query": "pasta"})]
    assert out["reply"].startswith("I found 1 dishes at Demo Bistro")


def test_llm_search_with_no_keywords_still_runs(llm_on):
    llm_on(StubBedrock("search_menu", {}))
    world = FakeWorld()
    world.ask("show me the menu")
    assert world.calls == [("search_menu", {"query": ""})]


def test_llm_uses_remembered_ids_and_tells_the_model_about_them(llm_on):
    stub = llm_on(StubBedrock("get_order_status", {}))
    world = FakeWorld()
    out = world.ask("where is my order", memory={"ids": {BISTRO.uuid: {"order_id": "A2001"}}})
    assert world.calls[-1] == ("get_order_status", {"order_id": "A2001"})
    assert "out for delivery" in out["reply"]
    assert "order_id = A2001" in stub.sent[0]["system"][0]["text"]


def test_llm_missing_required_value_is_asked_for(llm_on):
    llm_on(StubBedrock("get_order_status", {"order_id": "  "}))
    out = FakeWorld().ask("where is my order")
    assert out["kind"] == "clarify" and "order" in out["reply"].lower()


def test_llm_plain_reply_is_returned_without_a_tool_call(llm_on):
    llm_on(StubBedrock(text="You're welcome! I can help with Demo Bistro."))
    world = FakeWorld()
    out = world.ask("thanks a lot")
    assert out["kind"] == "none" and out["reply"].startswith("You're welcome") and world.calls == []


def test_llm_choice_of_a_blocked_service_explains_why(llm_on):
    llm_on(StubBedrock("next_available", {}))
    out = FakeWorld().ask("when can I get my teeth cleaned")
    assert out["kind"] == "blocked" and "connect Lakeside Dental" in out["reply"]


def test_llm_failure_falls_back_to_the_rules(llm_on):
    llm_on(StubBedrock(fail=RuntimeError("ThrottlingException")))
    world = FakeWorld()
    out = world.ask("what pasta does Demo Bistro have")
    assert world.calls == [("search_menu", {"query": "pasta"})]
    assert out["reply"].startswith("I found 1 dishes at Demo Bistro")


def test_rules_are_the_default(monkeypatch):
    from backend.app.assistant import llm

    monkeypatch.delenv("ASSISTANT", raising=False)
    assert not llm.enabled()


def test_tool_names_are_unique_and_bedrock_safe():
    from backend.app.assistant import llm

    specs, index = llm.build_tools(SERVICES + SERVICES)  # the same services twice
    names = [s["toolSpec"]["name"] for s in specs]
    assert len(names) == len(set(names)) == len(index)
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", n) for n in names)


def test_llm_thinking_text_never_reaches_the_user(llm_on):
    llm_on(StubBedrock(text="<thinking>The user said thanks. I will reply briefly.</thinking>\nYou're welcome!"))
    out = FakeWorld().ask("thanks")
    assert out["reply"] == "You're welcome!"


def test_llm_reply_that_is_only_thinking_falls_back_to_the_rules(llm_on):
    llm_on(StubBedrock(text="<thinking>I need a query to search the menu."))
    world = FakeWorld()
    world.ask("what pasta does Demo Bistro have")
    assert world.calls == [("search_menu", {"query": "pasta"})]


def test_llm_search_query_is_optional_for_the_model(llm_on):
    from backend.app.assistant import llm

    specs, _ = llm.build_tools(SERVICES)
    search = next(s["toolSpec"] for s in specs if s["toolSpec"]["name"].endswith("__search_menu"))
    assert "required" not in search["inputSchema"]["json"]
    assert "list everything" in search["description"]
    order = next(s["toolSpec"] for s in specs if s["toolSpec"]["name"].endswith("__get_order_status"))
    assert order["inputSchema"]["json"]["required"] == ["order_id"]  # real ids stay required


# ---- conversation memory: recent turns + a rolling summary (history.py) ----

class ScriptedBedrock:
    """Routes with the next scripted tool call; answers summary requests (no toolConfig)."""

    def __init__(self, calls, summary="SUMMARY", fail_summary=False):
        self.calls, self.summary, self.fail_summary = list(calls), summary, fail_summary
        self.routed, self.summarised = [], []

    def converse(self, **kw):
        if "toolConfig" not in kw:  # the summariser
            self.summarised.append(kw)
            if self.fail_summary:
                raise RuntimeError("ThrottlingException")
            return {"output": {"message": {"role": "assistant", "content": [{"text": self.summary}]}}}
        self.routed.append(kw)
        tool, args = self.calls.pop(0)
        name = next(t["toolSpec"]["name"] for t in kw["toolConfig"]["tools"]
                    if t["toolSpec"]["name"].endswith("__" + tool))
        block = {"toolUse": {"toolUseId": "t", "name": name, "input": args}}
        return {"output": {"message": {"role": "assistant", "content": [block]}}}


def test_model_gets_the_earlier_turns_so_follow_ups_resolve(llm_on):
    stub = llm_on(ScriptedBedrock([("search_menu", {"query": "dessert"}),
                                   ("place_order", {"item": "Tiramisu", "quantity": 2})]))
    world = FakeWorld()
    first = world.ask("anything in dessert?")
    out = world.ask("okay order 2 for me", memory=first["memory"])
    assert out["kind"] == "confirm" and "2 × Tiramisu" in out["reply"]  # no "what would you like?"
    sent = stub.routed[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"][0]["text"] == "anything in dessert?"
    assert sent[1]["content"][0]["text"] == "I found 1 dishes at Demo Bistro, including Tiramisu."  # no notes in it
    record = stub.routed[1]["system"][0]["text"]  # the record of what ran is in the system prompt
    assert 'ran Demo Bistro/search_menu {"query": "dessert"}' in record and "shown: Tiramisu" in record
    assert sent[2]["content"][0]["text"] == "okay order 2 for me"


def test_old_turns_are_folded_into_a_summary_and_sent_as_context(llm_on):
    from backend.app.assistant import history

    stub = llm_on(ScriptedBedrock([("search_menu", {})] * 5, summary="User browsed the menu."))
    world, memory = FakeWorld(), {}
    for i in range(4):
        memory = world.ask(f"show me the menu {i}", memory=memory)["memory"]
    assert stub.summarised, "the oldest messages should have been summarised"
    assert memory["_summary"] == "User browsed the menu."
    assert len(history.recent(memory)) <= history.TRIGGER
    world.ask("and again", memory=memory)
    assert "Summary of the earlier conversation: User browsed the menu." in stub.routed[-1]["system"][0]["text"]
    assert len(stub.routed[-1]["messages"]) <= history.TRIGGER + 1


def test_a_failed_summary_never_breaks_the_turn(llm_on):
    llm_on(ScriptedBedrock([("search_menu", {})] * 4, fail_summary=True))
    world, memory = FakeWorld(), {}
    for i in range(4):
        out = world.ask(f"menu please {i}", memory=memory)
        assert out["kind"] == "answer"
        memory = out["memory"]
    assert "Earlier the user asked" in memory["_summary"]


def test_memory_bookkeeping_is_not_a_known_value_or_tool_argument(llm_on):
    stub = llm_on(ScriptedBedrock([("search_menu", {}), ("get_order_status", {})]))
    world = FakeWorld()
    first = world.ask("show me the menu", memory={"ids": {BISTRO.uuid: {"order_id": "A2001"}}})
    world.ask("where is my order", memory=first["memory"])
    system = stub.routed[1]["system"][0]["text"]
    assert "order_id = A2001" in system and "_recent" not in system and "_summary" not in system
    assert world.calls[-1] == ("get_order_status", {"order_id": "A2001"})


def test_history_messages_alternate_and_start_with_the_user():
    from backend.app.assistant import history

    memory = {"_recent": [{"role": "assistant", "text": "Hi"}, {"role": "user", "text": "a"},
                          {"role": "user", "text": "b"}, {"role": "assistant", "text": "c"},
                          {"role": "bogus", "text": "x"}, "junk"]}
    roles = [m["role"] for m in history.messages(memory, "now")]
    assert roles == ["user", "assistant", "user"]
    assert history.messages({}, "hello") == [{"role": "user", "content": [{"text": "hello"}]}]


def test_rules_mode_keeps_no_history(monkeypatch):
    monkeypatch.delenv("ASSISTANT", raising=False)
    out = FakeWorld().ask("what pasta does Demo Bistro have")
    assert "_recent" not in out["memory"] and "_summary" not in out["memory"]


# ---- one conversation, several services ----

class MultiWorld(FakeWorld):
    """Like FakeWorld, but every call is recorded with the service it went to."""

    def call(self, service, tool, args):
        if service.name == "Lakeside Dental" and tool.name == "next_available":
            self.calls.append((service.name, tool.name, args))
            return {"data": {"slots": [{"slot_id": "slot_0914", "time": "9:00 AM"}]}, "is_error": False, "text": "ok"}
        if service.name == "Lakeside Dental" and tool.name == "book_appointment":
            self.calls.append((service.name, tool.name, args))
            return {"data": {"appointment_id": "apt_900", **args}, "is_error": False, "text": "ok"}
        res = super().call(service, tool, args)
        self.calls[-1] = (service.name, *self.calls[-1])
        return res


def _delivery() -> engine.ServiceInfo:
    """A second service whose tool also takes an `order_id`, to prove ids stay with their service."""
    twin = BISTRO.tools[1]  # get_order_status
    profile = dict(twin.profile, example_args={"order_id": "D77"}, example_phrases=[
        p.replace("Demo Bistro", "Quick Delivery") for p in twin.profile["example_phrases"]])
    tool = engine.ToolInfo("get_order_status", twin.title, twin.description, True, twin.params, profile)
    return engine.ServiceInfo("dddddddd-0000-0000-0000-000000000001", "Quick Delivery",
                              {"phrases": ["track my delivery"]}, [tool])


BOTH = ("Demo Bistro", "Lakeside Dental")


def test_one_conversation_moves_between_services_and_back():
    world, memory = MultiWorld(live=BOTH), {}
    out = world.ask("what pasta does Demo Bistro have", memory=memory)
    assert world.calls == [("Demo Bistro", "search_menu", {"query": "pasta"})]
    assert out["reply"].startswith("I found 1 dishes at Demo Bistro")
    assert out["via"] == {"service": "Demo Bistro", "tool": "search_menu", "switched": False}

    out = world.ask("when is the next cleaning at Lakeside Dental", memory=out["memory"])  # -> Dental
    assert world.calls[-1] == ("Lakeside Dental", "next_available", {"visit_type": "cleaning"})
    assert out["kind"] == "answer" and out["reply"].startswith("Lakeside Dental:")  # says where it came from
    assert out["via"] == {"service": "Lakeside Dental", "tool": "next_available", "switched": True}

    out = world.ask("what dessert does Demo Bistro have", memory=out["memory"])  # -> back to the Bistro
    assert world.calls[-1] == ("Demo Bistro", "search_menu", {"query": "dessert"})
    assert "Demo Bistro" in out["reply"] and out["via"]["switched"] is True
    assert [c[0] for c in world.calls] == ["Demo Bistro", "Lakeside Dental", "Demo Bistro"]


def test_each_service_remembers_its_own_ids_across_switches():
    world = MultiWorld(live=BOTH)
    order = world.ask("order 2 tiramisu from Demo Bistro")
    done = world.ask("yes", pending=order["pending"], memory=order["memory"])
    booking = world.ask("book slot_0914 at Lakeside Dental", memory=done["memory"])
    assert booking["kind"] == "confirm" and booking["pending"]["service_uuid"] == DENTAL.uuid
    booked = world.ask("yes", pending=booking["pending"], memory=booking["memory"])
    assert booked["memory"]["ids"] == {BISTRO.uuid: {"order_id": "A2001"}, DENTAL.uuid: {"appointment_id": "apt_900", "slot_id": "slot_0914"}}
    follow = world.ask("where is my Demo Bistro order", memory=booked["memory"])
    assert world.calls[-1] == ("Demo Bistro", "get_order_status", {"order_id": "A2001"})
    assert "out for delivery" in follow["reply"]


def test_ids_do_not_leak_into_another_services_tool():
    delivery = _delivery()
    services = SERVICES + [delivery]
    world = MultiWorld(live=("Demo Bistro", "Quick Delivery"))
    order = world.ask("order 2 tiramisu from Demo Bistro", services=services)
    done = world.ask("yes", pending=order["pending"], memory=order["memory"], services=services)
    assert done["memory"]["ids"] == {BISTRO.uuid: {"order_id": "A2001"}}
    before = len(world.calls)
    out = world.ask("what is the status of my Quick Delivery order", memory=done["memory"], services=services)
    assert out["kind"] == "clarify" and "Order ID" in out["reply"]  # it must ask, not reuse A2001
    assert len(world.calls) == before  # nothing was sent to either service
    out = world.ask("where is my Demo Bistro order", memory=done["memory"], services=services)
    assert world.calls[-1] == ("Demo Bistro", "get_order_status", {"order_id": "A2001"})
    assert "out for delivery" in out["reply"]


def test_memory_from_the_client_is_validated():
    world = MultiWorld()
    for junk in ({"ids": "oops"}, {"ids": {BISTRO.uuid: "x", 5: {}}}, {"_last_service": 7, "_choose": "x"}):
        assert world.ask("what pasta does Demo Bistro have", memory=junk)["kind"] == "answer"


@pytest.mark.parametrize("state, words", [
    ("not_connected", "connect Lakeside Dental"), ("expired", "reconnect"),
    ("not_published", "isn't published"), ("off", "switched off"),
])
def test_switch_to_a_service_that_is_not_usable_is_blocked_and_the_chat_continues(state, words):
    world = MultiWorld(live=("Demo Bistro",), states={"Lakeside Dental": state})
    first = world.ask("what pasta does Demo Bistro have")
    out = world.ask("when is the next cleaning at Lakeside Dental", memory=first["memory"])
    assert out["kind"] == "blocked" and words in out["reply"] and out["link"]
    assert out["service"]["name"] == "Lakeside Dental"
    assert [c[0] for c in world.calls] == ["Demo Bistro"]  # no Dental call, no fallback to the Bistro
    # the previous service is still the one used last, and the conversation goes on
    again = world.ask("what dessert does Demo Bistro have", memory=out["memory"])
    assert again["kind"] == "answer" and world.calls[-1][0] == "Demo Bistro"


def test_a_confirmation_is_dropped_when_the_user_changes_topic():
    world = MultiWorld(live=BOTH)
    for said, service, tool in [
        ("okay book a dentist appointment", "Lakeside Dental", "book_appointment"),  # starts with "okay"
        ("cancel my Lakeside Dental appointment apt_5521", "Lakeside Dental", "cancel_appointment"),
        ("no, what pasta does Demo Bistro have", "Demo Bistro", "search_menu"),
    ]:
        order = world.ask("order 2 tiramisu from Demo Bistro")
        assert order["kind"] == "confirm" and order["pending"]["tool"] == "place_order"
        world.calls.clear()
        out = world.ask(said, pending=order["pending"], memory=order["memory"])
        assert out["pending"] is None or out["pending"]["service_uuid"] == next(
            s.uuid for s in SERVICES if s.name == service)
        assert not any(c[1] == "place_order" for c in world.calls)  # the Bistro order never ran
        assert out["via"]["service"] == service and out["via"]["tool"] == tool
        assert out["kind"] in ("confirm", "clarify", "answer")  # the new request was routed, not "Okay, I won't"


@pytest.mark.parametrize("said", ["yes", "Yes", "yes please", "ok", "sure thing".replace(" thing", ""), "go ahead"])
def test_a_plain_yes_still_confirms_the_pending_action(said):
    world = MultiWorld(live=BOTH)
    order = world.ask("order 2 tiramisu from Demo Bistro")
    out = world.ask(said, pending=order["pending"], memory=order["memory"])
    assert ("Demo Bistro", "place_order", {"item": "Tiramisu", "quantity": 2}) in world.calls
    assert out["reply"] == "Demo Bistro: Done. Order A2001: 2 × Tiramisu. It should be ready in about 30 minutes."


@pytest.mark.parametrize("said", ["no", "No thanks", "cancel", "never mind", "stop"])
def test_a_plain_no_cancels_the_pending_action(said):
    world = MultiWorld(live=BOTH)
    order = world.ask("order 2 tiramisu from Demo Bistro")
    out = world.ask(said, pending=order["pending"], memory=order["memory"])
    assert out["reply"] == "Okay, I won't do that." and not any(c[1] == "place_order" for c in world.calls)


def test_a_confirmation_for_a_service_that_went_offline_is_not_run():
    order = MultiWorld(live=BOTH).ask("order 2 tiramisu from Demo Bistro")
    world = MultiWorld(live=("Lakeside Dental",), states={"Demo Bistro": "expired"})  # expired meanwhile
    out = world.ask("yes", pending=order["pending"], memory=order["memory"])
    assert out["kind"] == "blocked" and "reconnect" in out["reply"] and world.calls == []


def test_ambiguous_service_name_asks_which_and_the_answer_runs_the_request():
    world = MultiWorld(live=("Demo Bistro", "Lakeside Dental", "Lakeside Grill"))
    ask = world.ask("book an appointment at lakeside")
    assert ask["kind"] == "clarify" and world.calls == []
    assert ask["reply"] in ("Do you mean Lakeside Dental or Lakeside Grill?", "Do you mean Lakeside Grill or Lakeside Dental?")
    out = world.ask("the dental one", memory=ask["memory"])  # runs the original request, on Dental only
    assert out["via"]["service"] == "Lakeside Dental" and out["via"]["tool"] == "book_appointment"
    assert "_choose" not in out["memory"]
    ask = world.ask("book a time at lakeside")
    out = world.ask("grill", memory=ask["memory"])
    assert out["via"]["service"] == "Lakeside Grill" and out["via"]["tool"] == "book_table"
    assert world.calls == []  # both still need details before anything runs


def test_just_a_shared_name_asks_which_then_waits_for_the_task():
    world = MultiWorld(live=("Lakeside Dental", "Lakeside Grill"))
    ask = world.ask("lakeside")
    assert ask["kind"] == "clarify" and "Do you mean" in ask["reply"]
    out = world.ask("dental", memory=ask["memory"])
    assert out["reply"] == "Okay, Lakeside Dental. What would you like to do?" and world.calls == []
    assert world.ask("when is the next cleaning", memory=out["memory"])["via"]["service"] == "Lakeside Dental"


def test_ignoring_the_which_question_starts_a_new_request():
    world = MultiWorld(live=("Demo Bistro", "Lakeside Dental", "Lakeside Grill"))
    ask = world.ask("lakeside")
    out = world.ask("what pasta does Demo Bistro have", memory=ask["memory"])
    assert out["via"]["service"] == "Demo Bistro" and "_choose" not in out["memory"]


def test_a_clear_request_is_not_ambiguous_even_with_a_shared_name_word():
    world = MultiWorld(live=("Demo Bistro", "Lakeside Dental", "Lakeside Grill"))
    assert world.ask("what are the specials at lakeside")["via"]["service"] == "Lakeside Grill"
    assert world.ask("when is the next cleaning at Lakeside Dental")["via"]["service"] == "Lakeside Dental"


def test_the_last_service_only_breaks_an_exact_tie():
    delivery = _delivery()
    services = SERVICES + [delivery]
    world = MultiWorld(live=("Demo Bistro", "Quick Delivery"))
    phrase = "what's the status of my order"
    assert engine.score(phrase, BISTRO, BISTRO.tools[1]) == engine.score(phrase, delivery, delivery.tools[0])
    asked = world.ask(phrase, services=services)  # no history: ask which
    assert asked["kind"] == "clarify" and "Quick Delivery" in asked["reply"] and "Demo Bistro" in asked["reply"]
    for last, expected in [(delivery.uuid, "Quick Delivery"), (BISTRO.uuid, "Demo Bistro")]:
        out = world.ask(phrase, memory={"_last_service": last}, services=services)
        assert out["via"]["service"] == expected
    # ...but what the user says beats the last service
    out = world.ask("where is my Demo Bistro order", memory={"_last_service": delivery.uuid}, services=services)
    assert out["via"]["service"] == "Demo Bistro"


def test_llm_routes_each_turn_to_the_service_the_user_asks_for(llm_on):
    stub = llm_on(ScriptedBedrock([("search_menu", {"query": "pasta"}), ("next_available", {"visit_type": "cleaning"}),
                                   ("search_menu", {})]))
    world, memory = MultiWorld(live=BOTH), {}
    for said in ["what pasta do you have", "when can I get my teeth cleaned", "back to the menu"]:
        out = world.ask(said, memory=memory)
        memory = out["memory"]
    assert [c[0] for c in world.calls] == ["Demo Bistro", "Lakeside Dental", "Demo Bistro"]
    assert "The service used last was Demo Bistro" in stub.routed[1]["system"][0]["text"]
    names = [t["toolSpec"]["name"] for t in stub.routed[1]["toolConfig"]["tools"]]
    assert any(n.startswith("demo_bistro__") for n in names) and any(n.startswith("lakeside_dental__") for n in names)


def test_llm_known_ids_are_labelled_with_their_service(llm_on):
    stub = llm_on(ScriptedBedrock([("get_order_status", {})]))
    memory = {"ids": {BISTRO.uuid: {"order_id": "A2001"}, DENTAL.uuid: {"appointment_id": "apt_900"}}}
    MultiWorld(live=BOTH).ask("where is my order", memory=memory)
    system = stub.routed[0]["system"][0]["text"]
    assert "[Demo Bistro] order_id = A2001" in system and "[Lakeside Dental] appointment_id = apt_900" in system


def test_history_never_shows_the_model_its_own_turns_with_tool_notes(llm_on):
    """Regression: with "answer [ran tool]" in its past messages the model started writing such
    answers itself instead of calling the tool, so nothing ran and the results were made up."""
    stub = llm_on(ScriptedBedrock([("search_menu", {"query": "dessert"}), ("search_menu", {"query": "salad"})]))
    world = FakeWorld()
    first = world.ask("are there more desserts from this store?")
    world.ask("no its fine ill take salads, list me its options", memory=first["memory"])
    for m in stub.routed[1]["messages"]:
        assert "[" not in m["content"][0]["text"] and "ran " not in m["content"][0]["text"]
    assert [c[0] for c in world.calls] == ["search_menu", "search_menu"]  # the tool really ran again


def test_a_made_up_answer_without_a_tool_call_is_replaced_by_the_real_tool(llm_on):
    llm_on(StubBedrock(text="I found 1 salad at Demo Bistro, including Caesar Salad. [ran Demo Bistro/search_menu]"))
    world = FakeWorld()
    out = world.ask("what salads does Demo Bistro have")
    assert [c[0] for c in world.calls] == ["search_menu"]  # nothing was invented: the tool ran
    # the menu has no salad: the real answer is the business's "nothing found", not the invented dish
    assert out["reply"] == "I couldn't find any dishes matching that." and out.get("call")
    assert "Caesar" not in out["reply"] and "[ran" not in out["reply"]


def test_a_question_from_the_model_is_still_kept(llm_on):
    llm_on(StubBedrock(text="Which order do you mean?"))
    world = FakeWorld()
    out = world.ask("what is the status of order A1042")  # the rules would match, but the model asked
    assert out["kind"] == "none" and out["reply"] == "Which order do you mean?" and world.calls == []


def test_record_tags_copied_from_old_history_are_stripped():
    from backend.app.assistant import llm

    assert llm.clean_text("Sure. [ran Demo Bistro/search_menu {}] [showed: Tiramisu (6.5)]") == "Sure."
