"""Connector manifest -> C1 spec -> mapped tools, the 8 checks, and answer templates."""
import copy
import json
from pathlib import Path

import pytest

from backend.app.assistant.speech import render, speak
from backend.app.mapper import map_service
from backend.app.spec import parse_spec
from backend.app.submissions.manifest import (
    manifest_to_spec,
    run_checks,
    spec_to_manifest,
    tools_from_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
PINE = json.loads((ROOT / "backend/app/db/registry/manifests/pine_and_petal_1.0.json").read_text(encoding="utf-8"))
QUICKFIX = json.loads((ROOT / "backend/app/db/registry/manifests/quickfix_1.0.json").read_text(encoding="utf-8"))
BISTRO_SPEC = json.loads((ROOT / "mock-services/catalog/specs/demo_bistro.json").read_text(encoding="utf-8"))


def _statuses(report):
    return {c["id"]: c["status"] for c in report["checks"]}


def test_manifest_becomes_a_c1_spec_that_maps_to_tools():
    raw = manifest_to_spec(PINE, "77777777-7777-7777-7777-777777777777")
    spec = parse_spec(raw)
    assert (spec.service_name, spec.domain, spec.base_url) == ("Pine & Petal", "pinepetal.test",
                                                               "http://localhost:9300/florist")
    assert spec.oauth.scopes == ["shop"]
    mapped = map_service(spec)
    order = next(e for e in mapped.endpoints if e.tool_name == "order_bouquet")
    assert order.method == "POST" and not order.read_only
    assert [(p.name, p.location, p.required) for p in order.params] == [
        ("bouquet", "body", True), ("recipient", "body", True)]
    # Display and voice data travel with the spec into the registry.
    assert spec.profile["city"] == "Oak Park"
    assert spec.profile["tools"]["order_bouquet"]["confirmation_prompt"].startswith("Should I send")


def test_tools_resolve_refs_and_put_required_first():
    tools = {t["name"]: t for t in tools_from_manifest(PINE)}
    assert set(tools) == {"search_bouquets", "order_bouquet"}
    assert tools["search_bouquets"]["read_only"] and tools["search_bouquets"]["params"][0]["required"] is False
    assert tools["order_bouquet"]["side_effect"] == "payment"


def test_good_manifest_passes_with_local_warnings_only():
    report = run_checks(PINE)
    assert report["passed"] and report["version"] == "1.0"
    assert _statuses(report) == {"schema": "ok", "openapi": "ok", "https": "warn", "hosted": "warn",
                                 "domain": "warn", "voice": "ok", "confirm": "ok", "limit": "ok"}


def test_bad_manifest_fails_the_right_checks():
    report = run_checks(QUICKFIX)
    assert not report["passed"]
    failed = {k for k, v in _statuses(report).items() if v == "err"}
    assert {"https", "domain", "voice", "confirm"} <= failed


@pytest.mark.parametrize("breakage, check", [
    (lambda m: m.pop("accountLinking"), "schema"),
    (lambda m: m["openapi"]["paths"]["/bouquets"]["get"].pop("operationId"), "openapi"),
    (lambda m: m["openapi"]["paths"]["/orders"]["post"]["x-alexa"].pop("confirmationPrompt"), "confirm"),
    (lambda m: m["openapi"]["paths"]["/bouquets"]["get"]["x-alexa"].update(examplePhrases=["one"]), "voice"),
    (lambda m: m["openapi"]["servers"][0].update(url="http://api.elsewhere.com"), "https"),
])
def test_each_check_catches_its_problem(breakage, check):
    manifest = copy.deepcopy(PINE)
    breakage(manifest)
    report = run_checks(manifest)
    assert _statuses(report)[check] == "err" and not report["passed"]


def test_garbage_gets_a_report_not_an_exception():
    report = run_checks(["not", "a", "manifest"])
    assert not report["passed"] and all(c["status"] == "err" for c in report["checks"])


def test_catalog_spec_round_trips_through_a_manifest():
    manifest = spec_to_manifest(BISTRO_SPEC, "1.0", owner_email="o@x.example",
                                test_account={"username": "reviewer@demobistro.test", "password": "x"})
    assert run_checks(manifest)["passed"]
    again = parse_spec(manifest_to_spec(manifest, BISTRO_SPEC["service_uuid"]))
    assert [e.id for e in again.endpoints] == [e["id"] for e in BISTRO_SPEC["endpoints"]]
    assert map_service(again).endpoints == map_service(parse_spec(BISTRO_SPEC)).endpoints


def test_answer_templates():
    data = {"order_id": "A1", "results": [{"name": "Pasta"}, {"name": "Pizza"}, {"name": "Salad"}, {"name": "X"}]}
    assert render("Order {order_id}: {count:results} hits, {list:results.name}.", data) == \
        "Order A1: 4 hits, Pasta, Pizza and Salad."
    assert render("Order {order_id} is {missing}.", data) == "Order A1 is."
    profile = {"speakable_response": "{count:results} found", "empty_response": "Nothing.",
               "error_responses": {"404": "Not found."}}
    assert speak(profile, {"results": []}, is_error=False, status=200) == "Nothing."
    assert speak(profile, {}, is_error=True, status=404) == "Not found."
    assert speak(profile, {}, is_error=True, status=500, fallback="Oops.") == "Oops."
