import asyncio

import pytest

from backend.app.codegen.verifier import hit_endpoint as he
from backend.app.codegen.verifier.patch_issue import PatchInputError, debug_using_llm
from backend.app.codegen.verifier.utilities import verify_changes

SRC = '''import json
from runtime.auth_context import get_current_token


async def get_thing(thing_id: str) -> str:
    """Get a thing."""
    token = get_current_token()
    path = "/thngs/{thing_id}".format(thing_id=thing_id)
    return json.dumps({"path": path, "t": token})
'''
FIXED = SRC.replace("/thngs/", "/things/")
CHANGE = {"old": "/thngs/", "new": "/things/", "line": 8, "reason": "typo in path"}
ENDPOINT = {"tool_name": "get_thing", "method": "GET", "path_template": "/things/{thing_id}", "params": []}
REPORT = "Tool: get_thing\nInput: {}\nOutput received: null\nError: 404"


class PatchStub:
    def __init__(self, patch):
        self.patch = patch
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        use = {"toolUse": {"name": "submit_patch", "input": self.patch}}
        return {"output": {"message": {"content": [use]}}}


@pytest.fixture
def seeded(cache):
    cache.set_source("demo_bistro", "get_thing", SRC)
    cache.set_endpoint("demo_bistro", "get_thing", ENDPOINT)
    return cache


def test_cache_prev_backup_and_name_validation(cache):
    cache.set_source("demo_bistro", "get_thing", "v1")
    assert cache.get_previous_source("demo_bistro", "get_thing") is None
    cache.set_source("demo_bistro", "get_thing", "v2")
    assert cache.get_source("demo_bistro", "get_thing") == "v2"
    assert cache.get_previous_source("demo_bistro", "get_thing") == "v1"
    with pytest.raises(ValueError):
        cache.get_source("../x", "get_thing")


def test_verify_exact_change_is_verified_and_stored(seeded):
    out = verify_changes("demo_bistro", "get_thing", [CHANGE], FIXED, cache=seeded)
    assert out["status"] == "verified" and out["corrected"] is False
    assert seeded.get_source("demo_bistro", "get_thing") == FIXED
    assert seeded.get_previous_source("demo_bistro", "get_thing") == SRC


def test_verify_extra_edit_is_rebuilt_from_old_version(seeded):
    sneaky = FIXED.replace('"""Get a thing."""', '"""Get a thing, fast."""')
    out = verify_changes("demo_bistro", "get_thing", [CHANGE], sneaky, cache=seeded)
    assert out["status"] == "verified" and out["corrected"] is True
    assert out["source"] == FIXED
    assert seeded.get_source("demo_bistro", "get_thing") == FIXED


def test_verify_listed_change_missing_from_patched_file_is_rebuilt(seeded):
    out = verify_changes("demo_bistro", "get_thing", [CHANGE], SRC, cache=seeded)
    assert out["status"] == "verified" and out["corrected"] is True and out["source"] == FIXED


@pytest.mark.parametrize(
    "change",
    [
        {**CHANGE, "line": 7},  # off by one
        {**CHANGE, "line": 9},
        {**CHANGE, "old": "/nowhere/"},  # not in file
        {**CHANGE, "old": "thing_id", "new": "x"},  # appears more than once
    ],
)
def test_verify_rejects_inexact_changes(seeded, change):
    out = verify_changes("demo_bistro", "get_thing", [change], FIXED, cache=seeded)
    assert out["status"] == "not_verified"
    assert seeded.get_source("demo_bistro", "get_thing") == SRC


def test_verify_rejects_syntax_error(seeded):
    bad = {"old": "/thngs/", "new": '/things/"(', "line": 8, "reason": "x"}
    out = verify_changes("demo_bistro", "get_thing", [bad], SRC.replace("/thngs/", '/things/"('), cache=seeded)
    assert out["status"] == "not_verified" and "compile" in out["reason"]
    assert seeded.get_source("demo_bistro", "get_thing") == SRC


def test_verify_rejects_token_parameter_and_lost_slot_read(seeded):
    add_param = {"old": "async def get_thing(thing_id", "new": "async def get_thing(token, thing_id", "line": 5, "reason": "x"}
    out = verify_changes(
        "demo_bistro", "get_thing", [add_param], SRC.replace("get_thing(thing_id", "get_thing(token, thing_id"), cache=seeded
    )
    assert out["status"] == "not_verified" and "must not take a 'token' parameter" in out["reason"]

    drop_read = {"old": "    token = get_current_token()\n", "new": '    token = "x"\n', "line": 7, "reason": "x"}
    out = verify_changes(
        "demo_bistro", "get_thing", [drop_read], SRC.replace("token = get_current_token()", 'token = "x"'), cache=seeded
    )
    assert out["status"] == "not_verified" and "get_current_token()" in out["reason"]
    assert seeded.get_source("demo_bistro", "get_thing") == SRC


def test_debug_using_llm_patches_cache_and_returns_source(seeded):
    client = PatchStub({"patched_source": FIXED, "changes": [CHANGE]})
    out = asyncio.run(debug_using_llm(REPORT, "demo_bistro", "get_thing", cache=seeded, client=client))
    assert out == FIXED and seeded.get_source("demo_bistro", "get_thing") == FIXED
    prompt = client.calls[0]["messages"][0]["content"][0]["text"]
    assert REPORT in prompt and SRC in prompt and "/things/{thing_id}" in prompt
    assert "MINIMAL" in prompt and "path_template" in prompt
    assert client.calls[0]["toolConfig"]["toolChoice"] == {"tool": {"name": "submit_patch"}}


def test_debug_using_llm_returns_none_for_bad_patch(seeded):
    bad = {"patched_source": FIXED, "changes": [{**CHANGE, "line": 99}]}
    out = asyncio.run(debug_using_llm(REPORT, "demo_bistro", "get_thing", cache=seeded, client=PatchStub(bad)))
    assert out is None and seeded.get_source("demo_bistro", "get_thing") == SRC


@pytest.mark.parametrize("missing", ["report", "endpoint JSON", "tool source"])
def test_missing_inputs_raise_before_any_llm_call(cache, missing):
    if missing != "tool source":
        cache.set_source("demo_bistro", "get_thing", SRC)
    if missing != "endpoint JSON":
        cache.set_endpoint("demo_bistro", "get_thing", ENDPOINT)
    client = PatchStub({})
    report = "" if missing == "report" else REPORT
    with pytest.raises(PatchInputError, match=missing):
        asyncio.run(debug_using_llm(report, "demo_bistro", "get_thing", cache=cache, client=client))
    assert client.calls == []


def test_end_to_end_failing_tool_is_patched_then_verified(seeded, monkeypatch):
    """Attempt 1 fails (typo path), the patch call fixes it, attempt 2 verifies."""
    src = SRC.replace('{"path": path, "t": token}', '{"message": "404 " + path, "status": 404}')
    fixed = src.replace("/thngs/", "/things/").replace('{"message": "404 " + path, "status": 404}', '{"path": path, "t": token}')
    seeded.set_source("demo_bistro", "get_thing", src)
    change_a = {"old": "/thngs/", "new": "/things/", "line": 8, "reason": "typo"}
    change_b = {
        "old": '{"message": "404 " + path, "status": 404}', "new": '{"path": path, "t": token}', "line": 9, "reason": "ok body",
    }

    class Stub:
        calls = 0

        def converse(self, **kwargs):
            Stub.calls += 1
            name = kwargs["toolConfig"]["tools"][0]["toolSpec"]["name"]
            if name == "submit_patch":
                inp = {"patched_source": fixed, "changes": [change_a, change_b]}
            else:
                inp = {"thing_id": "A1"}
            return {"output": {"message": {"content": [{"toolUse": {"name": name, "input": inp}}]}}}

    async def no_notify(*a, **kw):
        raise AssertionError("must not notify")

    monkeypatch.setattr(he, "notify_unresolved", no_notify)
    out = asyncio.run(
        he.hit_endpoint("demo_bistro", "get_thing", token="secret-dev", cache=seeded, client=Stub())
    )
    assert out == "verified" and Stub.calls == 3  # test, patch, test
    assert seeded.get_source("demo_bistro", "get_thing") == fixed
