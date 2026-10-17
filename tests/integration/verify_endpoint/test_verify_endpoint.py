"""Integration test: URL / endpoint verification with the service's `_dev` token.

WHAT THIS CHECKS
  hit_endpoint(service, tool) end to end against a real (fake) HTTP endpoint:
    mapped JSON -> real generator (create_folders.sh) -> real seed_cache (real Redis)
    -> hit_endpoint: scripted "LLM" picks the arguments, the generated tool calls the fake
       restaurant API with the dev token read from DEMO_BISTRO_DEV_TOKEN.
  success: the API accepts the dev token -> outcome "verified", exactly one request reached the
           API and it carried "Bearer demo-dev-token", and no email was sent.
  failure: a wrong dev token -> the API answers 401 on all 5 attempts. The real retry loop runs
           (5 tool calls, 5 patch attempts that the scripted LLM answers with an empty patch),
           the report names HTTP 401, and notify_unresolved saves ONE email to the Amazon
           support address with get_order_status.py attached (no business uuid in this case).
  Both compare the observed behaviour with expected/<case>/result.json.

run_integration(case) returns True when the observed result matches the expected file.
Inputs are described in inputs/README.md. Needs Redis and jq. Bedrock is never called.
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from backend.app.codegen.verifier.hit_endpoint import hit_endpoint
from tests.integration.harness import (
    CASES,
    FakeApi,
    ScriptedBedrock,
    assert_case,
    compare_json,
    email_summary,
    generate_and_seed,
    load_json,
    main,
    outbox_emails,
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
    llm = ScriptedBedrock(load_json(inputs / "llm_script.json"))  # stands in for Bedrock
    env = load_json(inputs / "env.json")  # the dev token the provider created + support address
    setup = load_json(inputs / "setup.json")  # which tool to verify

    with FakeApi(routes) as api, redis_cache() as cache, tempfile.TemporaryDirectory() as tmp:
        mapped = render_mapped(inputs, api.url)  # point the generated tools at the fake API
        with patched_env({"GENERATED_DIR": tmp, "MODE": None, **env}):
            # setup: emulate the steps that run before verification (real generator + cache seeding)
            generate_and_seed(mapped, Path(tmp) / "out", cache)

            # the function under test, called the way the pipeline calls it (token from the env)
            outcome = asyncio.run(hit_endpoint(
                setup["service_name"], setup["tool_name"], cache=cache, client=llm,
                service_uuid=setup["service_uuid"],
            ))
            emails = outbox_emails(tmp)

    verified = outcome == "verified"
    actual = {
        "outcome": "verified" if verified else outcome["status"],
        "llm_call_sequence": llm.sequence,
        "api_requests": api.requests,
        "failure_mentions_http_401": False if verified else "HTTP status 401" in outcome["detail"],
        "emails": [
            {"to": s["to"], "cc": s["cc"], "attachments": s["attachments"]}
            for s in map(email_summary, emails)
        ],
    }
    return compare_json(actual, expected / "result.json")


@pytest.mark.parametrize("case", CASES)
def test_integration(case):
    assert_case(run_integration, case)


if __name__ == "__main__":
    main(run_integration)
