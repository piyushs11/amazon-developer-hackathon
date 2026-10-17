"""Shared helpers for the integration tests.

Every integration test (one folder per component) follows the same contract:

    <component>/inputs/<case>/     input files that feed the function under test
    <component>/expected/<case>/   the expected output files
    run_integration(case) -> bool  True when the real output matches the expected files

This module holds what they share: loading inputs, comparing outputs with expected files
(printing a readable diff on mismatch), a fake restaurant API, a scripted stand-in for the LLM,
and the prerequisite checks (Redis, jq) that turn into pytest skips.
"""

import difflib
import json
import os
import shutil
import sys
import threading
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).parent
TEST_REDIS_URL = "redis://localhost:6379/15"
CASES = ("success", "failure")


class PrerequisiteMissing(Exception):
    """Something the test needs (Redis, jq) is not available; pytest reports a skip."""


# ---- inputs / environment ---------------------------------------------------------------------


def load_json(path) -> object:
    return json.loads(Path(path).read_text())


@contextmanager
def patched_env(values: dict):
    """Set environment variables for a block (a None value removes the variable), then restore."""
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def require_jq() -> None:
    if shutil.which("jq") is None:
        raise PrerequisiteMissing("jq is required by create_folders.sh (brew install jq)")


@contextmanager
def redis_cache():
    """A ToolCache on the real local Redis (db 15, unique key prefix), cleaned up afterwards."""
    import uuid

    import redis

    from backend.app.storage.tool_cache import ToolCache

    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as e:
        raise PrerequisiteMissing("Redis is not running on localhost:6379 (brew services start redis)") from e
    cache = ToolCache(client, prefix=f"itest-{uuid.uuid4().hex[:8]}")
    try:
        yield cache
    finally:
        cache.delete_all()


def generate_and_seed(mapped: dict, out_dir, cache) -> tuple[str, list[str]]:
    """Emulate the pipeline steps before verification/storage: run the real generator on the
    mapped JSON and load the generated tool files + endpoint JSON into the Redis cache."""
    from backend.app.codegen.verifier.utilities import service_slug
    from backend.app.pipeline import flow_onboard as fo

    service_name = service_slug(mapped["service_name"])
    fo.generate(mapped, str(out_dir))
    return service_name, fo.seed_cache(service_name, mapped, str(out_dir), cache)


# ---- comparing output with expected files -----------------------------------------------------


def _show_diff(label: str, actual_text: str, expected_text: str) -> None:
    diff = difflib.unified_diff(
        expected_text.splitlines(), actual_text.splitlines(), "expected", "actual", lineterm=""
    )
    print(f"MISMATCH in {label}:\n" + "\n".join(diff), file=sys.stderr)


def compare_json(actual, expected_path) -> bool:
    expected = load_json(expected_path)
    if actual == expected:
        return True
    _show_diff(
        str(expected_path),
        json.dumps(actual, indent=2, sort_keys=True), json.dumps(expected, indent=2, sort_keys=True),
    )
    return False


def compare_text(actual: str, expected_path) -> bool:
    expected = Path(expected_path).read_text()
    if actual == expected:
        return True
    _show_diff(str(expected_path), actual, expected)
    return False


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def compare_tree(actual_dir, expected_dir) -> bool:
    """Same files, same contents (byte for byte) under both folders."""
    actual, expected = _tree(Path(actual_dir)), _tree(Path(expected_dir))
    ok = True
    for name in sorted(set(actual) | set(expected)):
        if name not in expected:
            print(f"UNEXPECTED file: {name}", file=sys.stderr)
            ok = False
        elif name not in actual:
            print(f"MISSING file: {name}", file=sys.stderr)
            ok = False
        elif actual[name] != expected[name]:
            _show_diff(name, actual[name], expected[name])
            ok = False
    return ok


# ---- fake restaurant API ----------------------------------------------------------------------


class FakeApi:
    """A throwaway local HTTP server standing in for the business's API.

    `routes` come from an input file: [{"method", "path", "requires_token" (str or list, optional),
    "status", "body"}]. A route that requires a token answers 401 unless the request carries
    `Authorization: Bearer <one of them>`. Every request is recorded in `self.requests`.
    """

    def __init__(self, routes: list[dict]):
        self.routes = routes
        self.requests: list[dict] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                path = urlsplit(self.path).path
                auth = self.headers.get("Authorization")
                api.requests.append({"method": self.command, "path": path, "authorization": auth})
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                route = next((r for r in api.routes if r["method"] == self.command and r["path"] == path), None)
                if route is None:
                    status, body = 404, {"error": "not found"}
                else:
                    allowed = route.get("requires_token")
                    allowed = [allowed] if isinstance(allowed, str) else allowed
                    if allowed and auth not in [f"Bearer {t}" for t in allowed]:
                        status, body = 401, {"error": "unauthorized"}
                    else:
                        status, body = route["status"], route["body"]
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

            def log_message(self, *args):  # keep test output quiet
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False


def render_mapped(inputs_dir, api_url: str) -> dict:
    """Load mapped_service.json, filling the ${FAKE_API_URL} placeholder with the fake API's URL."""
    return json.loads((Path(inputs_dir) / "mapped_service.json").read_text().replace("${FAKE_API_URL}", api_url))


# ---- scripted stand-in for the LLM (Bedrock) --------------------------------------------------


class ScriptedBedrock:
    """Replaces Bedrock. `script` maps a tool-name prefix (or "submit_patch") to the arguments the
    "LLM" chooses. Records the name of every tool it was asked to call."""

    def __init__(self, script: dict):
        self.script = script
        self.sequence: list[str] = []

    def converse(self, **kwargs):
        name = kwargs["toolConfig"]["tools"][0]["toolSpec"]["name"]
        self.sequence.append(name)
        key = name if name in self.script else next(k for k in self.script if name.startswith(k))
        return {"output": {"message": {"content": [{"toolUse": {"name": name, "input": self.script[key]}}]}}}


# ---- emails -----------------------------------------------------------------------------------


def parse_eml(path):
    return BytesParser(policy=policy.default).parsebytes(Path(path).read_bytes())


def email_summary(msg) -> dict:
    """The stable parts of an email (Date and Message-ID are left out on purpose)."""
    return {
        "from": msg["From"], "to": msg["To"], "cc": msg["Cc"], "subject": msg["Subject"],
        "body": msg.get_body(("plain",)).get_content(),
        "attachments": [part.get_filename() for part in msg.iter_attachments()],
    }


def outbox_emails(generated_dir) -> list:
    folder = Path(generated_dir) / "outbox"
    return [parse_eml(p) for p in sorted(folder.glob("*.eml"))] if folder.exists() else []


# ---- running a case ---------------------------------------------------------------------------


def assert_case(run_integration, case: str) -> None:
    """pytest wrapper: skip if a prerequisite is missing, otherwise the case must return True."""
    import pytest

    try:
        result = run_integration(case)
    except PrerequisiteMissing as e:
        pytest.skip(str(e))
    assert result is True, f"integration case {case!r} did not match its expected output (diff above)"


def main(run_integration, cases=CASES) -> None:
    """`python -m tests.integration.<component>.<module>`: run every case, print PASS/FAIL."""
    all_ok = True
    for case in cases:
        try:
            ok = run_integration(case)
        except PrerequisiteMissing as e:
            print(f"SKIP  {case}: {e}")
            continue
        print(f"{'PASS' if ok else 'FAIL'}  {case}")
        all_ok = all_ok and ok
    sys.exit(0 if all_ok else 1)
