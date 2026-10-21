"""Integration test: the runtime tool call, call_api (runtime/client.py).

WHAT THIS CHECKS
  A user's tool call from the LLM's choice down to the business API:
    setup (emulating earlier steps): mapped JSON -> real generator -> seed_cache -> real
      persist_verified writes the verified bundle to LocalStorage; the OAuth step is emulated by
      writing the users' tokens where get_user_token reads them (creds/users/<uuid>/<user>.json).
    call_api(ctx, tool_name, args): fetches the user's token, reads the latest bundle's tool file
      from storage, loads it (test loader standing in for Dev 3's runtime/loader.py), and runs
      it with the token set just before the API call.
  success: alice calls get_order_status; the hostile "token": "EVIL" the LLM sent is ignored, the
           API sees "Bearer alice-token", and the tool's response comes back unchanged
           (expected/success/result.json).
  failure: carol never connected her account, so call_api answers the 401 "Please connect this
           service in MCP Bridge first." failure JSON and NOTHING reaches the API.

run_integration(case) returns True when the real output matches the expected file.
Inputs are described in inputs/README.md. Needs Redis and jq. No network, AWS or Bedrock.
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from backend.app.codegen.verifier.hit_endpoint import _load_tool
from backend.app.pipeline.flow_onboard import persist_verified
from backend.app.storage.add_n_read_mcp_tool import LocalStorage
from runtime import client
from runtime.client import CallContext, call_api
from tests.integration.harness import (
    CASES,
    FakeApi,
    assert_case,
    compare_json,
    generate_and_seed,
    load_json,
    main,
    patched_env,
    redis_cache,
    render_mapped,
    require_jq,
)

HERE = Path(__file__).parent


def run_integration(case: str) -> bool:
    require_jq()
    inputs, expected = HERE / "inputs" / case, HERE / "expected" / case
    routes = load_json(inputs / "fake_api.json")["routes"]  # the business API
    tokens = load_json(inputs / "tokens.json")  # users who connected their account
    call = load_json(inputs / "call.json")  # what the gateway hands to call_api
    client._LOADED.clear()  # the tool-function cache is process-wide

    with FakeApi(routes) as api, redis_cache() as cache, tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mapped = render_mapped(inputs, api.url)
        with patched_env({"GENERATED_DIR": str(tmp), "MODE": None}):
            storage = LocalStorage.from_env()

            # setup 1: onboarding - generate, seed, mark every tool verified and store the bundle
            service_name, tool_names = generate_and_seed(mapped, tmp / "out", cache)
            verified = {t: {"status": "pass", "detail": "verified"} for t in tool_names}
            persist_verified(service_name, mapped["service_uuid"], verified, cache, storage)

            # setup 2: OAuth - each connected user's token is stored where get_user_token reads it
            for user, token in tokens.items():
                path = tmp / "creds" / "users" / mapped["service_uuid"] / f"{user}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"token": token}))

            # the function under test, called the way the gateway calls it
            response = asyncio.run(call_api(
                CallContext(**call["ctx"], base_url=api.url),  # the gateway adds the registry URL
                call["tool_name"], call["args"],
                storage=storage, tool_loader=_load_tool,
            ))

    actual = {"response": json.loads(response), "api_requests": api.requests}
    return compare_json(actual, expected / "result.json")


@pytest.mark.parametrize("case", CASES)
def test_integration(case):
    assert_case(run_integration, case)


if __name__ == "__main__":
    main(run_integration)
