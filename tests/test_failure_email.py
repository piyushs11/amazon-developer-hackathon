import asyncio
import os
import textwrap
from email import policy
from email.parser import BytesParser

import pytest

from backend.app.codegen.verifier import hit_endpoint as he
from backend.app.codegen.verifier import utilities as ut
from backend.app.codegen.verifier.utilities import (
    get_business_email,
    notify_unresolved,
    send_failure_email,
)
from backend.app.pipeline import flow_onboard as fo
from backend.app.storage.add_n_read_mcp_tool import LocalStorage

UUID = "11111111-1111-1111-1111-111111111111"
SOURCE = "async def get_thing(x):\n    return 'hello'\n"
REPORT = "Tool: get_thing\nInput: {}\nOutput received: null\nError: 404 Not Found"
ENDPOINT = {"method": "GET", "path_template": "/things/{thing_id}"}
AMAZON = "support@amazon.example"
BIZ = "owner@bistro.example"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.delenv("MODE", raising=False)
    monkeypatch.setenv("GENERATED_DIR", str(tmp_path))
    monkeypatch.setenv("AMAZON_SUPPORT_EMAIL", AMAZON)
    monkeypatch.delenv("ALERT_FROM_EMAIL", raising=False)


def _send(**kw):
    args = {"to_email": BIZ, "endpoint": ENDPOINT, **kw}
    return asyncio.run(send_failure_email("Demo Bistro", "get_thing", REPORT, SOURCE, **args))


def _saved(tmp_path):
    files = sorted((tmp_path / "outbox").glob("*.eml"))
    assert len(files) == 1
    return BytesParser(policy=policy.default).parsebytes(files[0].read_bytes())


# ---- get_business_email ---------------------------------------------------------------------


class FakeCursor:
    def __init__(self, row):
        self.row, self.executed = row, None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self, row):
        self.cursor_obj = FakeCursor(row)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self.cursor_obj


def test_business_email_found_and_parameterised():
    conn = FakeConn((" owner@bistro.example ",))
    assert get_business_email(UUID, connect=lambda: conn) == BIZ
    sql, params = conn.cursor_obj.executed
    assert "FROM businesses" in sql and "%s" in sql and params == (UUID,)  # never string-built


@pytest.mark.parametrize("row", [None, (None,), ("",), ("   ",)])
def test_business_email_missing(row):
    assert get_business_email(UUID, connect=lambda: FakeConn(row)) is None


def test_business_email_database_trouble_returns_none():
    def broken():
        raise ConnectionError("db down")

    assert get_business_email(UUID, connect=broken) is None
    assert get_business_email(None) is None


# ---- send_failure_email: local outbox -------------------------------------------------------


def test_local_outbox_email_content_and_attachment(tmp_path):
    assert _send() == "saved"
    msg = _saved(tmp_path)
    assert msg["Subject"] == "[MCP Bridge] Service endpoint could not be auto onboarded: Demo Bistro"
    assert msg["To"] == BIZ and msg["Cc"] == AMAZON and msg["From"] == "alerts@mcp-bridge.local"
    body = msg.get_body(("plain",)).get_content()
    assert "could not be auto onboarded. Please reverify the code and URLs." in body
    assert "Service:  Demo Bistro" in body
    assert "Endpoint: get_thing  (GET /things/{thing_id})" in body
    assert "Error: 404 Not Found" in body and "get_thing.py) is attached" in body
    (attachment,) = list(msg.iter_attachments())
    assert attachment.get_filename() == "get_thing.py"
    assert attachment.get_content() == SOURCE


def test_endpoint_line_without_endpoint_json(tmp_path):
    assert _send(endpoint=None) == "saved"
    assert "Endpoint: get_thing\n" in _saved(tmp_path).get_body(("plain",)).get_content()


def test_recipient_rules(tmp_path, monkeypatch):
    assert _send(to_email=None) == "saved"  # no business email: Amazon is the To
    msg = _saved(tmp_path)
    assert msg["To"] == AMAZON and msg["Cc"] is None
    for f in (tmp_path / "outbox").glob("*.eml"):
        f.unlink()
    assert _send(to_email=AMAZON.upper()) == "saved"  # same address twice: no duplicate Cc
    assert _saved(tmp_path)["Cc"] is None


def test_neither_address_is_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("AMAZON_SUPPORT_EMAIL")
    assert _send(to_email=None) == "skipped"
    assert not (tmp_path / "outbox").exists()


@pytest.mark.parametrize("bad", ["not-an-email", "a@b.com\nBcc: evil@x.com", "a@b", "x@y.com, z@y.com"])
def test_invalid_business_address_is_ignored(tmp_path, bad):
    assert _send(to_email=bad) == "saved"
    msg = _saved(tmp_path)
    assert msg["To"] == AMAZON and "evil" not in msg.as_string()


def test_newlines_in_names_cannot_inject_headers(tmp_path):
    asyncio.run(send_failure_email("Bistro\nBcc: evil@x.com", "get_thing", REPORT, SOURCE, to_email=BIZ))
    msg = _saved(tmp_path)
    assert msg["Bcc"] is None and "\n" not in msg["Subject"]


# ---- send_failure_email: SES ----------------------------------------------------------------


class FakeSES:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def send_raw_email(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error


def test_ses_send(monkeypatch):
    monkeypatch.setenv("ALERT_FROM_EMAIL", "alerts@verified.example")
    ses = FakeSES()
    assert _send(ses_client=ses) == "sent"
    (call,) = ses.calls
    assert call["Source"] == "alerts@verified.example" and call["Destinations"] == [BIZ, AMAZON]
    msg = BytesParser(policy=policy.default).parsebytes(call["RawMessage"]["Data"])
    assert msg["To"] == BIZ and next(msg.iter_attachments()).get_content() == SOURCE


def test_ses_without_sender_or_with_an_error_returns_failed(monkeypatch):
    assert _send(ses_client=FakeSES()) == "failed"  # ALERT_FROM_EMAIL not set
    monkeypatch.setenv("ALERT_FROM_EMAIL", "alerts@verified.example")
    assert _send(ses_client=FakeSES(error=RuntimeError("throttled"))) == "failed"


# ---- notify_unresolved + hit_endpoint -------------------------------------------------------


def test_notify_unresolved_looks_up_the_business(tmp_path, monkeypatch):
    looked_up = []
    monkeypatch.setattr(ut, "get_business_email", lambda uuid: looked_up.append(uuid) or BIZ)
    out = asyncio.run(notify_unresolved(
        "Demo Bistro", "get_thing", REPORT, service_uuid=UUID, source=SOURCE, endpoint=ENDPOINT
    ))
    assert out == "saved" and looked_up == [UUID]
    assert _saved(tmp_path)["To"] == BIZ


def test_notify_unresolved_without_uuid_goes_to_amazon(tmp_path):
    assert asyncio.run(notify_unresolved("Demo Bistro", "get_thing", REPORT)) == "saved"
    assert _saved(tmp_path)["To"] == AMAZON


def test_notify_unresolved_never_raises(monkeypatch):
    def boom(uuid):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(ut, "get_business_email", boom)
    assert asyncio.run(notify_unresolved("s", "t", REPORT, service_uuid=UUID)) == "failed"


FAIL_SRC = textwrap.dedent('''
    import json
    from runtime.auth_context import get_current_token

    async def get_thing(thing_id: str) -> str:
        """Get a thing.

        Args:
            thing_id: the id
        """
        return json.dumps({"message": "request failed " + get_current_token(), "status": 401})
''')


class StubBedrock:
    def converse(self, **kwargs):
        use = {"toolUse": {"name": "get_thing", "input": {"thing_id": "A1"}}}
        return {"output": {"message": {"content": [use]}}}


def test_hit_endpoint_emails_after_five_failures_with_latest_source(cache, tmp_path, monkeypatch):
    async def no_patch(*a, **kw):
        return None

    monkeypatch.setattr(he, "debug_using_llm", no_patch)
    monkeypatch.setattr(ut, "get_business_email", lambda uuid: BIZ)
    cache.set_source("demo_bistro", "get_thing", FAIL_SRC)
    cache.set_endpoint("demo_bistro", "get_thing", {"method": "GET", "path_template": "/things/{thing_id}"})
    out = asyncio.run(he.hit_endpoint(
        "demo_bistro", "get_thing", token="secret-dev", cache=cache, client=StubBedrock(), service_uuid=UUID
    ))
    assert out["status"] == "failed"
    msg = _saved(tmp_path)
    assert msg["To"] == BIZ and msg["Cc"] == AMAZON
    assert next(msg.iter_attachments()).get_content() == FAIL_SRC
    text = msg.as_string()
    assert "GET /things/{thing_id}" in msg.get_body(("plain",)).get_content()
    assert "secret-dev" not in text and "***" in msg.get_body(("plain",)).get_content()


def test_service_uuid_is_carried_from_generate_through_verify(cache, tmp_path, monkeypatch):
    seen = {}

    async def fake_verify(service_name, tool_names, **kwargs):
        seen.update(kwargs)
        return {"get_order_status": {"status": "pass", "detail": "verified"}}

    def fake_generate(mapped, out_dir):
        folder = tmp_path / "o" / "demo_bistro"
        folder.mkdir(parents=True)
        (folder / "get_order_status.py").write_text("async def get_order_status():\n    return 'a'\n")

    monkeypatch.setattr(fo, "generate", fake_generate)
    monkeypatch.setattr(fo, "verify_service", fake_verify)
    mapped = {"service_uuid": UUID, "service_name": "Demo Bistro",
              "endpoints": [{"endpoint_id": "get_order_status", "tool_name": "get_order_status",
                             "method": "GET", "path_template": "/orders/status"}]}
    asyncio.run(fo.onboard(mapped, str(tmp_path / "o"), cache=cache, storage=LocalStorage(tmp_path / "s")))
    assert seen["service_uuid"] == UUID


# ---- optional: real Postgres, TEMP table only -----------------------------------------------


def test_business_email_against_real_postgres_temp_table():
    psycopg = pytest.importorskip("psycopg")
    url = os.environ.get("DATABASE_URL", ut.DEFAULT_DATABASE_URL)
    try:
        conn = psycopg.connect(url, connect_timeout=2)
    except Exception:  # noqa: BLE001
        pytest.skip("Postgres is not reachable")

    class KeepOpen:
        def __enter__(self):
            return conn

        def __exit__(self, *a):
            return False

    try:
        with conn.cursor() as cur:  # TEMP table: lives only in this session, shadows `businesses`
            cur.execute(
                "CREATE TEMP TABLE businesses (service_uuid text primary key, business_name text,"
                " service_names text[], email text)"
            )
            cur.execute("INSERT INTO businesses VALUES (%s, %s, %s, %s)", (UUID, "Demo Bistro", ["Demo Bistro"], BIZ))
        assert get_business_email(UUID, connect=KeepOpen) == BIZ
        assert get_business_email("22222222-2222-2222-2222-222222222222", connect=KeepOpen) is None
    finally:
        conn.close()
