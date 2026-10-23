"""In-app notifications (the bell) and notice emails. Both are best effort: they never raise,
so a notification problem can't break a publish, a review decision or a tool call."""
import logging
import os
import re
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from backend.app.auth.settings import get_settings

log = logging.getLogger("mcp_bridge.notifications")
DEFAULT_SENDER = "MCP Bridge <no-reply@mcpbridge.local>"


def notify(user_id: str | None, kind: str, text: str, link: str | None = None) -> None:
    """Add a bell notification for this user. Needs the Postgres registry; otherwise a no-op."""
    if not user_id or get_settings().registry != "postgres":
        return
    try:
        from backend.app.db import portal

        portal.add_notification(user_id, kind, text, link)
    except Exception as exc:  # noqa: BLE001
        log.warning("notification %s for %s not stored: %s", kind, user_id, type(exc).__name__)


def send_notice_email(to: str | None, subject: str, body: str) -> str:
    """MODE=aws sends through SES; otherwise the email is saved as .eml in $GENERATED_DIR/outbox.
    Returns "sent", "saved", "skipped" or "failed"."""
    if not to or "@" not in to:
        return "skipped"
    try:
        sender = os.environ.get("ALERT_FROM_EMAIL") or DEFAULT_SENDER
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, to, subject
        cc = os.environ.get("AMAZON_SUPPORT_EMAIL")
        if cc and "@" in cc and cc.lower() != to.lower():
            msg["Cc"] = cc
        msg.set_content(body)
        if os.environ.get("MODE", "local") == "aws":
            import boto3

            boto3.client("ses").send_raw_email(
                Source=sender, Destinations=[a for a in (to, msg["Cc"]) if a], RawMessage={"Data": msg.as_bytes()})
            return "sent"
        folder = Path(os.environ.get("GENERATED_DIR", "generated")) / "outbox"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        (folder / re.sub(r"[^A-Za-z0-9_.-]", "_", f"{stamp}-{subject}.eml")[:150]).write_bytes(msg.as_bytes())
        return "saved"
    except Exception as exc:  # noqa: BLE001
        log.warning("notice email %r not sent: %s", subject, type(exc).__name__)
        return "failed"
