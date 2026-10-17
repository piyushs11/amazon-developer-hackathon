"""Integration test: failure email when a tool could not be auto-onboarded.

WHAT THIS CHECKS
  notify_unresolved(...) called exactly as hit_endpoint calls it after the 5th failed attempt
  (service_name, tool_name, report, service_uuid, source, endpoint), including the real
  get_business_email SQL path. The Postgres `businesses` table is emulated by
  inputs/<case>/businesses_table.json behind an injected connection, so no database is needed.
  success (transport "outbox", MODE=local): the business email is found by service uuid, one
           .eml is saved with From = ALERT_FROM_EMAIL, To = the business, Cc = the Amazon
           support address, the agreed subject and body (service, endpoint, issue), and the tool
           file attached with exactly the cached source
           (expected/success/email.json + expected/success/attachment.py).
  failure (transport "ses", MODE=aws): SES rejects the send (throttling). notify_unresolved must
           NOT raise, must report "failed", and nothing may be left in the outbox
           (expected/failure/email.json).

run_integration(case) returns True when the real output matches the expected files.
Inputs are described in inputs/README.md. No Redis, jq, AWS or database needed.
"""

import asyncio
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from backend.app.codegen.verifier import utilities as ut
from tests.integration.harness import (
    CASES,
    assert_case,
    compare_json,
    compare_text,
    email_summary,
    load_json,
    main,
    outbox_emails,
    patched_env,
)

HERE = Path(__file__).parent


class FakeBusinessesDb:
    """Stands in for Postgres: answers `SELECT email FROM businesses WHERE service_uuid = %s`."""

    def __init__(self, rows):
        self.rows = rows

    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        self._row = None
        return self

    def execute(self, sql, params):
        assert "FROM businesses" in sql and "WHERE service_uuid = %s" in sql  # the real query ran
        match = next((r for r in self.rows if r["service_uuid"] == params[0]), None)
        self._row = (match["email"],) if match else None

    def fetchone(self):
        return self._row


class RejectingSes:
    """An SES client that refuses every send, counting the attempts."""

    def __init__(self, message):
        self.message, self.attempts = message, 0

    def send_raw_email(self, **kwargs):
        self.attempts += 1
        raise RuntimeError(self.message)


def run_integration(case: str) -> bool:
    inputs, expected = HERE / "inputs" / case, HERE / "expected" / case
    call = load_json(inputs / "notify_call.json")  # arguments hit_endpoint passes
    source = (inputs / "source.py").read_text()  # latest tool source from the cache
    endpoint = load_json(inputs / "endpoint.json")  # endpoint JSON from the cache
    env = load_json(inputs / "env.json")
    transport = load_json(inputs / "transport.json")
    db = FakeBusinessesDb(load_json(inputs / "businesses_table.json"))
    ses = RejectingSes(transport["ses_error"]) if transport["transport"] == "ses" else None

    real_lookup, real_send = ut.get_business_email, ut.send_failure_email

    async def send_with_ses(*args, **kwargs):  # inject the SES client the way boto3 would supply it
        return await real_send(*args, ses_client=ses, **kwargs)

    with tempfile.TemporaryDirectory() as tmp, patched_env({"GENERATED_DIR": tmp, **env}):
        with (
            mock.patch.object(ut, "get_business_email", lambda uuid: real_lookup(uuid, connect=db.connect)),
            mock.patch.object(ut, "send_failure_email", send_with_ses if ses else real_send),
        ):
            status = asyncio.run(ut.notify_unresolved(
                call["service_name"], call["tool_name"], call["report"],
                service_uuid=call["service_uuid"], source=source, endpoint=endpoint,
            ))
        emails = outbox_emails(tmp)

    if transport["transport"] == "ses":
        # failure path: SES rejected the send, so we expect "failed", one attempt, and no file
        actual = {"status": status, "outbox_files": len(emails), "ses_send_attempts": ses.attempts}
        return compare_json(actual, expected / "email.json")

    # success path: exactly one email, matching the expected summary and attachment
    if len(emails) != 1:
        print(f"expected 1 email in the outbox, found {len(emails)}")
        return False
    attachment = next(emails[0].iter_attachments()).get_content()
    return (
        compare_json({"status": status, "email": email_summary(emails[0])}, expected / "email.json")
        & compare_text(attachment, expected / "attachment.py")
    )


@pytest.mark.parametrize("case", CASES)
def test_integration(case):
    assert_case(run_integration, case)


if __name__ == "__main__":
    main(run_integration)
