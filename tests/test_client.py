import asyncio
import json
import os
import types

import pytest

from backend.app.storage.add_n_read_mcp_tool import LocalStorage
from runtime import client
from runtime.client import CallContext, call_api

UUID = "11111111-1111-1111-1111-111111111111"
V1, V2 = "aaaaaaaaaaaa", "bbbbbbbbbbbb"

TOOL_SRC = '''import json
from runtime.auth_context import get_current_token


async def get_thing(thing_id: str) -> str:
    return json.dumps({"id": thing_id, "token": get_current_token(), "v": "1"})
'''


def loader(source: str, tool_name: str):
    """Stand-in for Dev 3's runtime/loader.py: compile the source and return its tool function."""
    module = types.ModuleType(f"_t_{tool_name}")
    exec(compile(source, f"<{tool_name}>", "exec"), module.__dict__)  # noqa: S102 - test stand-in
    return getattr(module, tool_name)


@pytest.fixture(autouse=True)
def _clear_loaded():
    client._LOADED.clear()
    yield
    client._LOADED.clear()


@pytest.fixture
def storage(tmp_path):
    store = LocalStorage(tmp_path / "bundles")
    store.write_bundle(UUID, V1, {"get_thing.py": TOOL_SRC})
    return store


def _call(storage, user="alice", tool="get_thing", args=None, fetcher=None, **kw):
    ctx = CallContext(user_id=user, service_uuid=UUID, request_id="r1")
    return asyncio.run(call_api(
        ctx, tool, {"thing_id": "A1"} if args is None else args, storage=storage,
        token_fetcher=fetcher or (lambda u, s: f"tok-{u}"), tool_loader=kw.pop("tool_loader", loader), **kw,
    ))


def test_tool_result_comes_back_unchanged(storage):
    out = _call(storage)
    assert out == json.dumps({"id": "A1", "token": "tok-alice", "v": "1"})


def test_fetcher_gets_user_and_service_uuid_and_llm_token_is_ignored(storage):
    seen = []

    def fetcher(user, service):
        seen.append((user, service))
        return "real-token"

    out = json.loads(_call(storage, args={"thing_id": "A1", "token": "EVIL"}, fetcher=fetcher))
    assert out["token"] == "real-token" and seen == [("alice", UUID)]


def test_async_token_fetcher_is_supported(storage):
    async def fetcher(user, service):
        return "async-token"

    assert json.loads(_call(storage, fetcher=fetcher))["token"] == "async-token"


def test_two_users_concurrently_get_their_own_tokens(storage):
    async def both():
        make = lambda u: call_api(
            CallContext(user_id=u, service_uuid=UUID), "get_thing", {"thing_id": u}, storage=storage,
            token_fetcher=lambda user, s: f"tok-{user}", tool_loader=loader,
        )
        return await asyncio.gather(make("alice"), make("bob"))

    alice, bob = (json.loads(r) for r in asyncio.run(both()))
    assert (alice["id"], alice["token"]) == ("alice", "tok-alice")
    assert (bob["id"], bob["token"]) == ("bob", "tok-bob")


def test_missing_token_stops_before_anything_is_loaded(storage):
    def exploding_loader(source, name):
        raise AssertionError("must not load")

    out = json.loads(_call(storage, fetcher=lambda u, s: None, tool_loader=exploding_loader))
    assert out == {"message": "Please connect this service in MCP Bridge first.", "status": 401}


def test_unpublished_service(tmp_path):
    empty = LocalStorage(tmp_path / "nothing")
    assert json.loads(_call(empty)) == {"message": "This service isn't published yet.", "status": 404}


@pytest.mark.parametrize("tool", ["nope", "../etc", "Bad-Name", "get_thing.py", ""])
def test_unknown_or_invalid_tool(storage, tool):
    out = json.loads(_call(storage, tool=tool))
    assert out["status"] == 404


def test_uses_the_latest_stored_version(storage):
    assert json.loads(_call(storage))["v"] == "1"
    path = storage.write_bundle(UUID, V2, {"get_thing.py": TOOL_SRC.replace('"v": "1"', '"v": "2"')})
    os.utime(storage.root / UUID / V1, ns=(1_000_000_000, 1_000_000_000))
    os.utime(path, ns=(2_000_000_000, 2_000_000_000))
    assert json.loads(_call(storage))["v"] == "2"


def test_function_is_loaded_once_per_version(storage):
    calls = []

    def counting_loader(source, name):
        calls.append(name)
        return loader(source, name)

    _call(storage, tool_loader=counting_loader)
    _call(storage, tool_loader=counting_loader)
    assert calls == ["get_thing"]


def test_no_loader_gives_a_clean_failure(storage):
    out = json.loads(asyncio.run(call_api(
        CallContext(user_id="alice", service_uuid=UUID), "get_thing", {"thing_id": "A1"},
        storage=storage, token_fetcher=lambda u, s: "t",
    )))
    assert out["status"] == 501 and "Dev 3" in out["message"]


def test_errors_are_short_and_never_contain_the_token(storage, tmp_path):
    storage.write_bundle(UUID, "cccccccccccc", {"get_thing.py": TOOL_SRC.replace(
        'return json.dumps({"id": thing_id, "token": get_current_token(), "v": "1"})',
        'raise ValueError("upstream rejected " + get_current_token())',
    )})
    out = json.loads(_call(storage, fetcher=lambda u, s: "super-secret"))
    assert out["status"] == 500 and "super-secret" not in out["message"] and "***" in out["message"]
    assert "Traceback" not in out["message"]


def test_timeout(storage):
    storage.write_bundle(UUID, "dddddddddddd", {"get_thing.py": TOOL_SRC.replace(
        "import json\n", "import asyncio, json\n").replace(
        "    return json.dumps(", "    await asyncio.sleep(1)\n    return json.dumps(")})
    out = json.loads(_call(storage, timeout=0.01))
    assert out["status"] == 504 and "timed out" in out["message"]


def test_logs_argument_names_not_values(storage, caplog):
    caplog.set_level("INFO", logger="runtime.client")
    _call(storage, args={"thing_id": "SENSITIVE-VALUE"})
    text = caplog.text
    assert "thing_id" in text and "SENSITIVE-VALUE" not in text and "tok-alice" not in text
