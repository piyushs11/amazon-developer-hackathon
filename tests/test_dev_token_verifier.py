import asyncio
import json
import textwrap

import pytest

from backend.app.codegen.verifier import hit_endpoint as he
from backend.app.codegen.verifier.utilities import verify_service
from backend.app.storage.read_cred_tokens import dev_key, get_dev_token

OK_SRC = textwrap.dedent('''
    import json
    from runtime.auth_context import get_current_token

    async def get_thing(thing_id: str) -> str:
        """Get a thing.

        Args:
            thing_id: the id
        """
        token = get_current_token()
        return json.dumps({"seen_token": token, "id": thing_id})
''')

FAIL_SRC = OK_SRC.replace(
    'return json.dumps({"seen_token": token, "id": thing_id})',
    'return json.dumps({"message": "request to get_thing failed " + token, "status": 401})',
)


class StubBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        use = {"toolUse": {"name": "get_thing", "input": {"thing_id": "A1"}}}
        return {"output": {"message": {"content": [use]}}}


@pytest.fixture
def hooks(monkeypatch):
    seen = {"debug": [], "notify": []}

    async def fake_debug(report, service, tool, **kwargs):
        seen["debug"].append(report)

    async def fake_notify(service, tool, report, **kwargs):
        seen["notify"].append(report)

    monkeypatch.setattr(he, "debug_using_llm", fake_debug)
    monkeypatch.setattr(he, "notify_unresolved", fake_notify)
    return seen


def _run(cache, client, **kw):
    return asyncio.run(
        he.hit_endpoint("demo_bistro", "get_thing", token="secret-dev", client=client, cache=cache, **kw)
    )


def test_dev_key_and_env_lookup(monkeypatch):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.setenv("DEMO_BISTRO_DEV_TOKEN", "t-123")
    assert dev_key("demo_bistro") == "demo_bistro_dev"
    assert get_dev_token("demo_bistro") == "t-123"


def test_file_lookup_and_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.delenv("DEMO_BISTRO_DEV_TOKEN", raising=False)
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    assert get_dev_token("demo_bistro") is None
    (tmp_path / "creds").mkdir()
    (tmp_path / "creds" / "demo_bistro_dev.json").write_text(json.dumps({"token": "from-file"}))
    assert get_dev_token("demo_bistro") == "from-file"


class _FakeSecrets:
    class exceptions:  # mimics the boto3 client attribute
        class ResourceNotFoundException(Exception):
            pass

    def __init__(self, value=None, error=None):
        self._value, self._error = value, error

    def get_secret_value(self, SecretId):
        if self._error:
            raise self._error
        if self._value is None:
            raise self.exceptions.ResourceNotFoundException()
        return {"SecretString": self._value}


def test_aws_dev_token_prefers_secrets_manager(monkeypatch):
    monkeypatch.setenv("MODE", "aws")
    monkeypatch.setenv("DEMO_BISTRO_DEV_TOKEN", "from-env")
    secrets = _FakeSecrets(json.dumps({"token": "from-secret"}))
    assert get_dev_token("demo_bistro", secrets_client=secrets) == "from-secret"


def test_aws_dev_token_falls_back_to_env_when_secret_missing(monkeypatch):
    monkeypatch.setenv("MODE", "aws")
    monkeypatch.setenv("DEMO_BISTRO_DEV_TOKEN", "from-env")
    assert get_dev_token("demo_bistro", secrets_client=_FakeSecrets()) == "from-env"


def test_aws_dev_token_falls_back_to_env_when_secrets_manager_errors(monkeypatch):
    monkeypatch.setenv("MODE", "aws")
    monkeypatch.setenv("DEMO_BISTRO_DEV_TOKEN", "from-env")
    broken = _FakeSecrets(error=RuntimeError("AccessDenied"))
    assert get_dev_token("demo_bistro", secrets_client=broken) == "from-env"


def test_aws_dev_token_none_when_nothing_configured(monkeypatch):
    monkeypatch.setenv("MODE", "aws")
    monkeypatch.delenv("DEMO_BISTRO_DEV_TOKEN", raising=False)
    assert get_dev_token("demo_bistro", secrets_client=_FakeSecrets()) is None


def test_invalid_service_name_rejected():
    with pytest.raises(ValueError):
        dev_key("../etc")


def test_success_is_verified_and_description_tagged(cache, hooks):
    cache.set_source("demo_bistro", "get_thing", OK_SRC)
    client = StubBedrock()
    assert _run(cache, client) == "verified"
    spec = client.calls[0]["toolConfig"]["tools"][0]["toolSpec"]
    assert spec["description"].endswith("Call this tool for the testing.")
    assert "token" not in spec["inputSchema"]["json"]["properties"]
    assert "read-only lookup" in client.calls[0]["messages"][0]["content"][0]["text"]
    assert hooks["debug"] == [] and hooks["notify"] == []


def test_parse_response():
    assert he.parse_response({"input": {}, "output": {"id": 1}, "error": None}) == "response_generated"
    assert he.parse_response({"input": {}, "output": None, "error": "boom"}) == "error"
    assert he.parse_response({"input": {}, "output": {"message": "x", "status": 500}, "error": None}) == "error"
    assert he.parse_response({"input": {}, "output": {}, "error": None}) == "error"


def test_failure_runs_five_attempts_then_notifies(cache, hooks):
    cache.set_source("demo_bistro", "get_thing", FAIL_SRC)
    client = StubBedrock()
    out = _run(cache, client)
    assert out["status"] == "failed"
    assert len(client.calls) == 5
    assert len(hooks["debug"]) == 5 and len(hooks["notify"]) == 1
    report = hooks["debug"][0]
    assert '{"thing_id": "A1"}' in report and "HTTP status 401" in report
    assert "check the tool definition" in report.lower()
    assert "secret-dev" not in out["detail"] and "***" in out["detail"]


def test_patched_source_is_reloaded_between_attempts(cache, monkeypatch):
    cache.set_source("demo_bistro", "get_thing", FAIL_SRC)
    notified = []

    async def patching_debug(report, service, tool, **kwargs):
        cache.set_source(service, tool, OK_SRC)

    async def fake_notify(*a, **kw):
        notified.append(a)

    monkeypatch.setattr(he, "debug_using_llm", patching_debug)
    monkeypatch.setattr(he, "notify_unresolved", fake_notify)
    client = StubBedrock()
    assert _run(cache, client) == "verified"
    assert len(client.calls) == 2 and notified == []


def test_missing_patch_inputs_do_not_crash_the_loop(cache, monkeypatch):
    """No endpoint JSON is cached, so the real debug_using_llm raises PatchInputError."""
    cache.set_source("demo_bistro", "get_thing", FAIL_SRC)
    notified = []

    async def fake_notify(service, tool, report, **kwargs):
        notified.append(report)

    monkeypatch.setattr(he, "notify_unresolved", fake_notify)
    client = StubBedrock()
    out = _run(cache, client)
    assert out["status"] == "failed" and "endpoint JSON" in out["detail"]
    assert len(client.calls) == 5 and len(notified) == 1  # no patch call: the stub only saw test calls


def test_missing_token_makes_no_llm_call(monkeypatch, hooks):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.delenv("DEMO_BISTRO_DEV_TOKEN", raising=False)
    monkeypatch.setenv("GENERATED_DIR", "/nonexistent-dir")
    client = StubBedrock()
    out = asyncio.run(he.hit_endpoint("demo_bistro", "get_thing", client=client))
    assert out["status"] == "failed" and "demo_bistro_dev" in out["detail"]
    assert client.calls == []


def test_verify_service_maps_results(cache, hooks):
    cache.set_source("demo_bistro", "get_thing", OK_SRC)
    out = asyncio.run(
        verify_service("demo_bistro", ["get_thing"], token="secret-dev", cache=cache, client=StubBedrock())
    )
    assert out == {"get_thing": {"status": "pass", "detail": "verified"}}
