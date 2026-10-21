# ruff: noqa: C408
import ast
import asyncio
import json

import pytest
from jinja2 import Template

from backend.app.codegen.templates.service_template import ENDPOINT_TEMPLATE
from backend.app.codegen.verifier import hit_endpoint as he
from backend.app.codegen.verifier.utilities import run_tool_call
from backend.app.storage.read_cred_tokens import get_user_token
from runtime.auth_context import (
    call_with_token,
    get_current_base_url,
    get_current_token,
    use_base_url,
    use_token,
)

TOOL_SRC = '''import json
from runtime.auth_context import get_current_token


async def get_thing(thing_id: str) -> str:
    """Get a thing."""
    return json.dumps({"id": thing_id, "token": get_current_token()})
'''


# ---- runtime.auth_context -------------------------------------------------------------------


def test_slot_unset_raises_and_is_reset_after_use():
    with pytest.raises(RuntimeError):
        get_current_token()
    with use_token("abc"):
        assert get_current_token() == "abc"
    with pytest.raises(RuntimeError):
        get_current_token()


def test_slot_is_reset_after_an_exception():
    with pytest.raises(ValueError), use_token("abc"):
        raise ValueError("boom")
    with pytest.raises(RuntimeError):
        get_current_token()


def test_concurrent_calls_see_only_their_own_token():
    async def tool(delay):
        await asyncio.sleep(delay)
        return get_current_token()

    async def main():
        return await asyncio.gather(
            call_with_token(tool, "alice-token", {"delay": 0.02}, 1),
            call_with_token(tool, "bob-token", {"delay": 0.01}, 1),
        )

    assert asyncio.run(main()) == ["alice-token", "bob-token"]


# ---- get_user_token -------------------------------------------------------------------------


def test_user_token_file_lookup_and_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    assert get_user_token("alice", "demo_bistro") is None
    folder = tmp_path / "creds" / "users" / "demo_bistro"
    folder.mkdir(parents=True)
    (folder / "alice.json").write_text(json.dumps({"token": "alice-token"}))
    assert get_user_token("alice", "demo_bistro") == "alice-token"
    assert get_user_token("bob", "demo_bistro") is None


def test_user_token_can_be_stored_under_a_service_uuid(monkeypatch, tmp_path):
    uuid = "11111111-1111-1111-1111-111111111111"
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    folder = tmp_path / "creds" / "users" / uuid
    folder.mkdir(parents=True)
    (folder / "alice.json").write_text(json.dumps({"token": "uuid-alice"}))
    assert get_user_token("alice", uuid) == "uuid-alice"
    assert get_user_token("bob", uuid) is None


def test_user_token_never_falls_back_to_the_dev_token(monkeypatch, tmp_path):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_BISTRO_DEV_TOKEN", "dev-secret")
    assert get_user_token("alice", "demo_bistro") is None


@pytest.mark.parametrize("user_id", ["../etc", "a/b", "", ".hidden", "x" * 65])
def test_user_token_rejects_bad_ids(user_id):
    with pytest.raises(ValueError):
        get_user_token(user_id, "demo_bistro")
    with pytest.raises(ValueError):
        get_user_token("alice", "../x")


def test_user_token_from_secrets_manager(monkeypatch):
    monkeypatch.setenv("MODE", "aws")

    class NotFound(Exception):
        pass

    class FakeSecrets:
        class exceptions:  # mirrors boto3's client.exceptions
            ResourceNotFoundException = NotFound

        def get_secret_value(self, SecretId):
            if SecretId != "mcp-bridge/demo_bistro/alice":
                raise NotFound()
            return {"SecretString": json.dumps({"token": "aws-alice"})}

    assert get_user_token("alice", "demo_bistro", secrets_client=FakeSecrets()) == "aws-alice"
    assert get_user_token("bob", "demo_bistro", secrets_client=FakeSecrets()) is None


# ---- run_tool_call --------------------------------------------------------------------------


@pytest.fixture
def tool_cache(cache):
    cache.set_source("demo_bistro", "get_thing", TOOL_SRC)
    return cache


def _run(tool_cache, user, args, fetcher):
    return asyncio.run(
        run_tool_call("demo_bistro", "get_thing", user, args, cache=tool_cache, token_fetcher=fetcher)
    )


def test_user_token_reaches_the_tool_and_llm_token_is_dropped(tool_cache):
    out = _run(tool_cache, "alice", {"thing_id": "A1", "token": "EVIL"}, lambda u, s: f"tok-{u}-{s}")
    assert json.loads(out) == {"id": "A1", "token": "tok-alice-demo_bistro"}


def test_two_users_get_two_different_tokens(tool_cache):
    async def both():
        return await asyncio.gather(
            run_tool_call("demo_bistro", "get_thing", "alice", {"thing_id": "1"}, cache=tool_cache,
                          token_fetcher=lambda u, s: f"tok-{u}"),
            run_tool_call("demo_bistro", "get_thing", "bob", {"thing_id": "2"}, cache=tool_cache,
                          token_fetcher=lambda u, s: f"tok-{u}"),
        )

    alice, bob = (json.loads(r) for r in asyncio.run(both()))
    assert alice["token"] == "tok-alice" and bob["token"] == "tok-bob"


def test_async_token_fetcher_is_supported(tool_cache):
    async def fetcher(user, service):
        return "async-token"

    assert json.loads(_run(tool_cache, "alice", {"thing_id": "A1"}, fetcher))["token"] == "async-token"


def test_default_fetcher_reads_user_token_from_storage(tool_cache, monkeypatch, tmp_path):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    folder = tmp_path / "creds" / "users" / "demo_bistro"
    folder.mkdir(parents=True)
    (folder / "alice.json").write_text(json.dumps({"token": "stored-alice"}))
    out = asyncio.run(run_tool_call("demo_bistro", "get_thing", "alice", {"thing_id": "A1"}, cache=tool_cache))
    assert json.loads(out)["token"] == "stored-alice"


def test_missing_token_asks_user_to_connect_without_running_the_tool(cache):
    # nothing cached for the tool: proves the tool is never even loaded
    out = _run(cache, "alice", {"thing_id": "A1"}, lambda u, s: None)
    assert json.loads(out) == {"message": "Please connect demo_bistro first.", "status": 401}


def test_errors_are_short_and_never_contain_the_token(cache):
    cache.set_source("demo_bistro", "get_thing", TOOL_SRC.replace(
        'return json.dumps({"id": thing_id, "token": get_current_token()})',
        'raise ValueError("upstream rejected " + get_current_token())',
    ))
    out = json.loads(_run(cache, "alice", {"thing_id": "A1"}, lambda u, s: "super-secret"))
    assert out["status"] == 500 and "super-secret" not in out["message"] and "***" in out["message"]


def test_timeout_is_reported(cache, monkeypatch):
    cache.set_source("demo_bistro", "get_thing", TOOL_SRC.replace(
        "import json\n", "import asyncio, json\n").replace(
        '    return json.dumps(', '    await asyncio.sleep(1)\n    return json.dumps('))
    monkeypatch.setattr(he, "CALL_TIMEOUT", 0.01)
    out = json.loads(_run(cache, "alice", {"thing_id": "A1"}, lambda u, s: "t"))
    assert out["status"] == 500 and "timed out" in out["message"]


# ---- template: the tool function has no token parameter ------------------------------------

ENDPOINTS = [
    dict(endpoint_id="get_order_status", tool_name="get_order_status", method="GET",
         description="Get the status of an order by its ID.", path_template="/orders/{order_id}",
         params=[dict(name="order_id", python_type="str", required=True, location="path",
                      description="Order ID, e.g. A1042")]),
    dict(endpoint_id="search_menu", tool_name="search_menu", method="GET", description="Find dishes.",
         path_template="/menu/search",
         params=[dict(name="query", python_type="str", required=False, location="query", description="Text"),
                 dict(name="limit", python_type="int", required=False, location="query", description="Max")]),
    dict(endpoint_id="ping", tool_name="ping", method="GET", description="Ping.", path_template="/ping",
         params=[]),
    dict(endpoint_id="place_order", tool_name="place_order", method="POST", description="Place an order.",
         path_template="/orders",
         params=[dict(name="note", python_type="str", required=False, location="body", description="Note"),
                 dict(name="item", python_type="str", required=True, location="body", description="Item")]),
]


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e["tool_name"])
def test_rendered_tool_takes_only_its_real_params(endpoint):
    source = Template(ENDPOINT_TEMPLATE).render(service_name="demo_bistro", base_url="http://x", **endpoint)
    tree = ast.parse(source)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    tool = funcs[f"{endpoint['tool_name']}fordemo_bistro"]
    names = [a.arg for a in tool.args.args]
    assert "token" not in names
    assert names == sorted((p["name"] for p in endpoint["params"]),
                           key=lambda n: not next(p for p in endpoint["params"] if p["name"] == n)["required"])
    assert "token" in [a.arg for a in funcs[f"{endpoint['endpoint_id']}_request"].args.args]
    assert "from runtime.auth_context import get_current_base_url, get_current_token" in source
    assert "token = get_current_token()" in source
    # the service URL is read at call time, never baked into the generated code
    assert "get_current_base_url()," in source
    assert "http://x" not in source


# ---- base URL slot (runtime approach: the URL is never baked into a tool) ----


def test_base_url_slot_is_scoped_and_trimmed():
    with pytest.raises(RuntimeError):
        get_current_base_url()
    with use_base_url("http://demo-api:9000/"):
        assert get_current_base_url() == "http://demo-api:9000"
    with pytest.raises(RuntimeError):
        get_current_base_url()


async def test_call_with_token_sets_base_url_per_call():
    async def tool(delay: float):
        await asyncio.sleep(delay)
        return get_current_base_url()

    a, b = await asyncio.gather(
        call_with_token(tool, "t", {"delay": 0.02}, 1, base_url="http://a.test"),
        call_with_token(tool, "t", {"delay": 0.01}, 1, base_url="http://b.test"),
    )
    assert (a, b) == ("http://a.test", "http://b.test")
    with pytest.raises(RuntimeError):  # no base_url given -> the tool cannot guess one
        await call_with_token(tool, "t", {"delay": 0}, 1)
