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

    def ask(self, text, pending=None, memory=None):
        return engine.answer(text=text, pending=pending, memory=memory or {}, services=SERVICES,
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
    out = world.ask("where is my order", memory={"order_id": "A2001"})
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
