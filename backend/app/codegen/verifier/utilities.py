"""Helpers for verifying and patching the generated tools of a service."""

import ast
import asyncio
import difflib
import inspect
import json
import logging
import os
import re
from datetime import UTC, datetime
from email.message import EmailMessage
from itertools import pairwise
from pathlib import Path

from backend.app.storage.read_cred_tokens import get_user_token
from backend.app.storage.tool_cache import ToolCache

log = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
MAX_DIFF_LINES = 12
DEFAULT_DATABASE_URL = "postgresql://mcpbridge:mcpbridge@localhost:5432/mcpbridge"
DEFAULT_SENDER = "alerts@mcp-bridge.local"
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

EMAIL_SUBJECT = "[MCP Bridge] Service endpoint could not be auto onboarded: {service_name}"
EMAIL_BODY = """\
The service endpoint could not be auto onboarded. Please reverify the code and URLs.

Service:  {service_name}
Endpoint: {endpoint}
Issue:
{report}

The tool file ({tool_name}.py) is attached.
"""


def bedrock_client(client=None):
    if client is not None:
        return client
    import boto3

    return boto3.client("bedrock-runtime")


def get_business_email(service_uuid: str | None, *, connect=None) -> str | None:
    """The business's email for `service_uuid` from the Postgres `businesses` table, or None.

    Expected table: businesses(service_uuid text primary key, business_name text,
    service_names text[], email text, ...). Any database problem returns None (logged), so a
    lookup failure never blocks the notification.
    """
    if not service_uuid:
        return None
    try:
        if connect is None:
            import psycopg

            def connect():
                return psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), connect_timeout=3)

        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT email FROM businesses WHERE service_uuid = %s", (service_uuid,))
            row = cur.fetchone()
    except Exception as e:  # noqa: BLE001 - lookup trouble must not break onboarding
        log.warning("business email lookup failed for %s: %s", service_uuid, type(e).__name__)
        return None
    email = row[0] if row else None
    return email.strip() if isinstance(email, str) and email.strip() else None


def _valid_email(address: str | None) -> str | None:
    address = (address or "").strip()
    if not address:
        return None
    if "\r" in address or "\n" in address or not _EMAIL.match(address):
        log.warning("ignoring invalid email address")
        return None
    return address


def _line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def _build_email(
    service_name: str, tool_name: str, report: str, source: str, endpoint: dict | None,
    sender: str, to: str, cc: str | None,
) -> EmailMessage:
    where = _line(tool_name)
    if endpoint and endpoint.get("method") and endpoint.get("path_template"):
        where = f"{where}  ({endpoint['method']} {endpoint['path_template']})"
    msg = EmailMessage()
    msg["Subject"] = EMAIL_SUBJECT.format(service_name=_line(service_name))
    msg["From"] = sender
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg.set_content(EMAIL_BODY.format(
        service_name=_line(service_name), endpoint=where, report=report, tool_name=_line(tool_name),
    ))
    msg.add_attachment(
        (source or "").encode(), maintype="text", subtype="x-python",
        filename=f"{re.sub(r'[^A-Za-z0-9_.-]', '_', tool_name)}.py",
    )
    return msg


async def send_failure_email(
    service_name: str, tool_name: str, report: str, source: str, *, to_email: str | None = None,
    default_email: str | None = None, endpoint: dict | None = None, ses_client=None, outbox_dir=None,
) -> str:
    """Email the failure report with the tool file attached. Never raises.

    The business (`to_email`) is the To address; `default_email` (default: env
    AMAZON_SUPPORT_EMAIL) is added as Cc, or becomes the To if there is no business address.
    MODE=aws sends through SES; otherwise the email is saved as a .eml file in the outbox.
    Returns "sent", "saved", "skipped" or "failed".
    """
    try:
        business = _valid_email(to_email)
        amazon = _valid_email(default_email or os.environ.get("AMAZON_SUPPORT_EMAIL"))
        if business and amazon and business.lower() != amazon.lower():
            to, cc = business, amazon
        else:
            to, cc = business or amazon, None
        if not to:
            log.warning("no recipient for the %s/%s failure email; skipped", service_name, tool_name)
            return "skipped"

        use_ses = ses_client is not None or os.environ.get("MODE", "local") == "aws"
        sender = os.environ.get("ALERT_FROM_EMAIL") or (None if use_ses else DEFAULT_SENDER)
        if not sender:
            log.warning("ALERT_FROM_EMAIL is not set; failure email not sent")
            return "failed"
        msg = _build_email(service_name, tool_name, report, source, endpoint, sender, to, cc)

        if use_ses:
            if ses_client is None:
                import boto3

                ses_client = boto3.client("ses")
            await asyncio.to_thread(
                ses_client.send_raw_email, Source=sender,
                Destinations=[a for a in (to, cc) if a], RawMessage={"Data": msg.as_bytes()},
            )
            return "sent"
        folder = Path(outbox_dir) if outbox_dir else Path(os.environ.get("GENERATED_DIR", "generated")) / "outbox"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{stamp}-{service_name}-{tool_name}.eml")
        (folder / name).write_bytes(msg.as_bytes())
        return "saved"
    except Exception as e:  # noqa: BLE001 - a mail problem must not break onboarding
        log.warning("failure email for %s/%s not sent: %s", service_name, tool_name, type(e).__name__)
        return "failed"


def store_failure(
    service_uuid: str, version: str, tool_name: str, report: str, source: str | None, error_storage=None
) -> bool:
    """Keep the failed tool and its report under {service_uuid}/{version}/ in error storage.

    Never raises; returns whether the files were stored.
    """
    try:
        from backend.app.storage.error_files import get_error_storage

        error_storage = error_storage or get_error_storage()
        error_storage.write_error(service_uuid, version, f"{tool_name}_failure.log", report)
        if source:
            error_storage.write_error(service_uuid, version, f"{tool_name}.py", source)
        return True
    except Exception as e:  # noqa: BLE001 - debugging aid, must not break onboarding
        log.warning("error files for %s/%s not stored: %s", service_uuid, tool_name, type(e).__name__)
        return False


async def notify_unresolved(
    service_name: str, tool_name: str, report: str, *, service_uuid: str | None = None,
    source: str | None = None, endpoint: dict | None = None,
) -> str:
    """Tell the business (and Amazon support) that a tool could not be auto-onboarded.

    Looks up the business email by service uuid, then sends the failure email with the tool
    file attached. Returns the email status; never raises.
    """
    try:
        business = await asyncio.to_thread(get_business_email, service_uuid) if service_uuid else None
        return await send_failure_email(
            service_name, tool_name, report, source or "", to_email=business, endpoint=endpoint
        )
    except Exception as e:  # noqa: BLE001
        log.warning("notify_unresolved failed for %s/%s: %s", service_name, tool_name, type(e).__name__)
        return "failed"


class MappedServiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def service_slug(service_name: str) -> str:
    """Identifier-safe service name; same rule as create_folders.sh (lowercase, non-alnum -> _)."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(service_name).lower()).strip("_")
    if not re.match(r"^[a-z_][a-z0-9_]*$", slug):
        raise ValueError(f"invalid service_name: {service_name!r}")
    return slug


def load_mapped_service(service_uuid: str, storage=None) -> dict:
    """Read the mapped service JSON (C2) stored for `service_uuid`, or raise MappedServiceError."""
    from backend.app.storage.add_n_read_mcp_tool import get_storage

    try:
        mapped = (storage or get_storage()).read_mapped(service_uuid)
    except json.JSONDecodeError as e:
        raise MappedServiceError("mapped_invalid", f"stored mapped JSON is not valid JSON: {e.msg}") from e
    except ValueError as e:
        raise MappedServiceError("invalid_service_uuid", str(e)) from e
    if mapped is None:
        raise MappedServiceError("mapped_not_found", f"no mapped service stored for {service_uuid}")
    if not isinstance(mapped, dict) or mapped.get("service_uuid") != service_uuid:
        raise MappedServiceError("mapped_invalid", "service_uuid inside the mapped JSON does not match")
    try:
        service_slug(mapped.get("service_name", ""))
    except ValueError as e:
        raise MappedServiceError("mapped_invalid", str(e)) from e
    endpoints = mapped.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise MappedServiceError("mapped_invalid", "the mapped JSON has no endpoints")
    for endpoint in endpoints:
        name = endpoint.get("tool_name") or endpoint.get("endpoint_id") if isinstance(endpoint, dict) else None
        if not isinstance(name, str) or not re.match(r"^[a-z_][a-z0-9_]*$", name):
            raise MappedServiceError("mapped_invalid", f"invalid endpoint name: {name!r}")
    return mapped


def _not_verified(reason: str) -> dict:
    return {"status": "not_verified", "source": None, "reason": reason, "corrected": False}


def _apply_changes(old: str, changes: list[dict]) -> tuple[str | None, str]:
    """Apply exact old->new snippets to `old`. Returns (new_source, error)."""
    if not changes:
        return None, "no changes were listed"
    spans = []
    for i, change in enumerate(changes, 1):
        snippet, replacement, line = change.get("old"), change.get("new"), change.get("line")
        if not isinstance(snippet, str) or not snippet or not isinstance(replacement, str):
            return None, f"change {i}: 'old' and 'new' must be strings and 'old' non-empty"
        found = old.count(snippet)
        if found != 1:
            return None, f"change {i}: 'old' snippet appears {found} times in the file, expected exactly 1"
        start = old.index(snippet)
        actual_line = old.count("\n", 0, start) + 1
        if line != actual_line:
            return None, f"change {i}: 'line' is {line} but the snippet starts on line {actual_line}"
        spans.append((start, start + len(snippet), replacement))
    spans.sort()
    for (_, prev_end, _), (next_start, _, _) in pairwise(spans):
        if next_start < prev_end:
            return None, "changes overlap"
    out, pos = [], 0
    for start, end, replacement in spans:
        out.append(old[pos:start])
        out.append(replacement)
        pos = end
    out.append(old[pos:])
    return "".join(out), ""


def _async_signatures(source: str) -> dict[str, set[str]]:
    tree = ast.parse(source)
    return {
        node.name: {a.arg for a in node.args.args + node.args.kwonlyargs}
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }


def verify_changes(
    service_name: str, tool_name: str, changes: list[dict], patched_source: str, *, cache: ToolCache
) -> dict:
    """Check the LLM's patch against its own list of changes and store it if it holds.

    The newest cached source is the base. Every change must match exactly (one occurrence,
    exact line). The patched file is compared with "base + listed changes"; any difference
    means the LLM changed something it did not declare, so the file is rebuilt from the base.
    Returns {"status": "verified" | "not_verified", "source", "reason", "corrected"}.
    """
    old = cache.get_source(service_name, tool_name)
    if old is None:
        return _not_verified("no cached source to compare against")

    rebuilt, error = _apply_changes(old, changes)
    if rebuilt is None:
        return _not_verified(error)

    corrected = rebuilt != patched_source
    reason = "changes match the patched file"
    if corrected:
        diff = list(
            difflib.unified_diff(
                rebuilt.splitlines(), str(patched_source).splitlines(),
                "listed changes", "patched file", lineterm="", n=0,
            )
        )
        shown = "\n".join(diff[:MAX_DIFF_LINES])
        reason = f"patched file differed from the listed changes; rebuilt from the previous version:\n{shown}"

    try:
        compile(rebuilt, f"<{tool_name}>", "exec")
        before, after = _async_signatures(old), _async_signatures(rebuilt)
    except SyntaxError as e:
        return _not_verified(f"patched code does not compile: {e.msg} (line {e.lineno})")
    for name in before:
        if name not in after:
            return _not_verified(f"function {name!r} was removed")
    for name, args in after.items():
        if "token" in args and not name.endswith("_request"):  # only the API helper takes it
            return _not_verified(f"function {name!r} must not take a 'token' parameter")
    if "get_current_token()" in old and "get_current_token()" not in rebuilt:
        return _not_verified("the tool must still read its token with get_current_token()")
    if "get_current_base_url()" in old and "get_current_base_url()" not in rebuilt:
        return _not_verified("the tool must still read the service URL with get_current_base_url()")

    cache.set_source(service_name, tool_name, rebuilt)
    return {"status": "verified", "source": rebuilt, "reason": reason, "corrected": corrected}


def _no_token_message(service_name: str) -> str:
    return json.dumps({"message": f"Please connect {service_name} first.", "status": 401})


async def run_tool_call(
    service_name: str, tool_name: str, user_id: str, llm_args: dict, *,
    cache: ToolCache | None = None, token_fetcher=None, base_url: str | None = None,
) -> str:
    """Run a tool the LLM picked, attaching THIS user's token just before the API call.

    The LLM only supplies the tool's real arguments: any `token` it sends is dropped. The
    token is fetched from storage (or `token_fetcher(user_id, service_name)`), put in the
    per-call slot, and read by the tool right before it calls the API. Returns the tool's
    JSON string, or the standard failure JSON; the token never appears in the result.
    """
    from runtime.auth_context import call_with_token

    from .hit_endpoint import CALL_TIMEOUT, tool_details

    args = {k: v for k, v in (llm_args or {}).items() if k != "token"}
    token = (token_fetcher or get_user_token)(user_id, service_name)
    if inspect.isawaitable(token):
        token = await token
    if not token:
        return _no_token_message(service_name)
    try:
        details = tool_details(service_name, tool_name, cache=cache or ToolCache.from_env())
        return await call_with_token(details.fn, token, args, CALL_TIMEOUT, base_url=base_url)
    except TimeoutError:
        message = f"the {tool_name} request timed out"
    except Exception as e:  # noqa: BLE001 - never leak a stack trace or the token to the caller
        message = f"{tool_name} failed: {type(e).__name__}: {str(e).replace(token, '***')[:200]}"
    return json.dumps({"message": message, "status": 500})


async def verify_service(
    service_name: str, tool_names: list[str], *, token: str | None = None,
    cache: ToolCache | None = None, client=None, model_id=None, service_uuid: str | None = None,
    version: str | None = None, base_url: str | None = None,
) -> dict:
    """Return {tool_name: {"status": "pass" | "fail", "detail": str}} for every tool."""
    from .hit_endpoint import VERIFIED, hit_endpoint

    results = {}
    for tool_name in tool_names:
        out = await hit_endpoint(
            service_name, tool_name, token=token, cache=cache, client=client, model_id=model_id,
            service_uuid=service_uuid, version=version, base_url=base_url,
        )
        results[tool_name] = (
            {"status": "pass", "detail": VERIFIED} if out == VERIFIED
            else {"status": "fail", "detail": out["detail"]}
        )
    return results
