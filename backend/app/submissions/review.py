"""Owner submissions and Amazon review: what the /owner and /review routes do. Blocking
(Postgres + HTTP); the routes call these from a thread.

    owner uploads a manifest -> run_checks -> submission (pending)
    reviewer: start -> try a tool against the real API with the test account -> approve | reject
    approve -> manifest_to_spec -> parse_spec -> map_service -> registry (+ business) => the
               service is in the catalog; users can find, connect and publish it
"""
import base64
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from backend.app.assistant.speech import speak
from backend.app.auth.settings import get_settings, rewrite
from backend.app.db import portal, registry
from backend.app.db.portal import SubmissionRow, UserRow
from backend.app.mapper import MapError, map_service
from backend.app.notifications import notify, send_notice_email
from backend.app.spec import SpecError, parse_spec
from backend.app.submissions.manifest import manifest_to_spec, run_checks, service_uuid_for

MIN_REASON = 20
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.\-]{0,31}$")


class ReviewError(Exception):
    """A request the caller can fix. `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---- views ----

def _check_counts(report: dict) -> dict:
    checks = report.get("checks") or []
    count = {s: sum(1 for c in checks if c.get("status") == s) for s in ("ok", "warn", "err")}
    return {"passed": bool(report.get("passed")), "total": len(checks), **count}


def _owner(user_id: str | None) -> dict | None:
    user = portal.get_user(user_id) if user_id else None
    return {"user_id": user.user_id, "display_name": user.display_name, "email": user.email} if user else None


def summary(row: SubmissionRow) -> dict:
    pub = row.manifest.get("publisher") or {}
    tools = row.check_report.get("tools") or []
    return {
        "id": row.id, "service_uuid": row.service_uuid, "service_name": row.service_name,
        "domain": row.domain, "version": row.version, "status": row.status,
        "submitted_at": row.submitted_at, "reviewed_at": row.reviewed_at,
        "assignee": row.assignee, "reviewer": row.reviewer, "reason": row.reason, "note": row.note,
        "message": row.message, "attachment_name": row.attachment_name,
        "category": pub.get("category", ""), "city": pub.get("city", ""),
        "description": pub.get("description", ""), "brand_color": pub.get("brandColor"),
        "owner": _owner(row.owner_user_id), "checks": _check_counts(row.check_report),
        "tools_count": len(tools), "write_count": sum(1 for t in tools if not t.get("read_only")),
    }


def _live(service_uuid: str) -> dict | None:
    from backend.app.api.catalog import _connected_users

    row = registry.get_service(service_uuid)
    if row is None:
        return None
    return {"in_catalog": True, "published": row.active_version is not None,
            "version": row.active_version, "published_at": row.published_at,
            "connected_users": _connected_users(service_uuid), "profile": row.profile or {}}


def detail(row: SubmissionRow) -> dict:
    history = [summary(s) for s in portal.list_submissions(domain=row.domain) if s.id != row.id]
    return {**summary(row), "manifest": row.manifest, "check_report": row.check_report,
            "history": history, "live": _live(row.service_uuid)}


# ---- owner ----

def owner_connectors(owner: UserRow) -> list[dict]:
    """Every service this owner manages: their businesses plus anything they've submitted."""
    by_domain: dict[str, dict] = {}
    for sub in portal.list_submissions(owner_user_id=owner.user_id):  # newest first
        c = by_domain.setdefault(sub.domain, {"service_uuid": sub.service_uuid, "service_name": sub.service_name,
                                              "domain": sub.domain, "submissions": []})
        c["submissions"].append(summary(sub))
    for biz in registry.list_businesses(owner_user_id=owner.user_id):
        row = registry.get_service(biz.service_uuid)
        if row and row.domain not in by_domain:
            by_domain[row.domain] = {"service_uuid": row.service_uuid, "service_name": row.service_name,
                                     "domain": row.domain, "submissions": []}
    out = []
    for c in by_domain.values():
        live = _live(c["service_uuid"])
        latest = c["submissions"][0] if c["submissions"] else None
        approved = next((s for s in c["submissions"] if s["status"] == "approved"), None)
        if latest and latest["status"] in ("pending", "in_review"):
            status = latest["status"]
        elif live:
            status = "live" if live["published"] else "approved"
        else:
            status = latest["status"] if latest else "draft"
        out.append({**c, "status": status, "live": live,
                    "live_version": approved["version"] if approved else None,
                    "category": (latest or {}).get("category") or ((live or {}).get("profile") or {}).get("category", ""),
                    "profile": (live or {}).get("profile") or {}})
    return sorted(out, key=lambda c: c["service_name"].lower())


def owner_connector(owner: UserRow, service_uuid: str) -> dict:
    match = next((c for c in owner_connectors(owner) if c["service_uuid"] == service_uuid), None)
    if match is None:
        raise ReviewError(404, "not one of your services")
    latest = portal.list_submissions(service_uuid=service_uuid)
    return {**match, "latest": detail(latest[0]) if latest else None}


def _store_attachment(submission_id: int, name: str, content_b64: str) -> str:
    try:
        data = base64.b64decode(content_b64, validate=True)
    except ValueError:
        raise ReviewError(422, "attachment: content must be base64") from None
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ReviewError(413, "attachment: 5 MB at most")
    if not data.startswith(b"%PDF"):
        raise ReviewError(422, "attachment: only PDF files")
    folder = Path(os.environ.get("GENERATED_DIR", "generated")) / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[-80:] or "attachment.pdf"
    path = folder / f"{submission_id}-{safe}"
    path.write_bytes(data)
    return str(path)


def submit(owner: UserRow, manifest: dict, message: str, attachment: dict | None) -> dict:
    report = run_checks(manifest)
    if not report["passed"]:
        failed = [c["title"] for c in report["checks"] if c["status"] == "err"]
        raise ReviewError(422, "Fix the failed checks first: " + "; ".join(failed))
    pub = manifest["publisher"]
    domain = pub["domain"].strip().lower()
    version = report["version"]
    if not _VERSION.match(version):
        raise ReviewError(422, "openapi.info.version must be like 1.0 or 1.1.2")
    # Only the business that owns a domain can submit for it.
    existing = registry.find_by_domain(domain)
    if existing:
        biz = registry.get_business(existing.service_uuid)
        if biz and biz.owner_user_id and biz.owner_user_id != owner.user_id:
            raise ReviewError(403, f"{domain} belongs to another business account")
    others = [s for s in portal.list_submissions(domain=domain) if s.owner_user_id not in (None, owner.user_id)]
    if others and not existing:
        raise ReviewError(403, f"{domain} was submitted by another business account")
    if portal.open_submission_for(domain):
        raise ReviewError(409, f"{domain} already has a submission waiting for review")
    row = portal.insert_submission(
        service_uuid=service_uuid_for(domain), service_name=pub["name"], domain=domain,
        owner_user_id=owner.user_id, version=version, manifest=manifest, check_report=report,
        message=(message or "")[:2000], attachment_name=(attachment or {}).get("name"),
    )
    if row is None:
        raise ReviewError(409, f"version {version} of {domain} was already submitted; bump openapi.info.version")
    if attachment and attachment.get("content_base64"):
        try:
            path = _store_attachment(row.id, attachment.get("name") or "attachment.pdf", attachment["content_base64"])
        except ReviewError:
            # The submission must not exist without its attachment.
            portal.update_submission(row.id, status="rejected", reason="attachment rejected", reviewed_at=_now())
            raise
        _set_attachment_path(row.id, path)
    for reviewer in portal.list_users("reviewer"):
        notify(reviewer.user_id, "submitted", f"{row.service_name} {row.version} is waiting for review.",
               f"/review/submissions/{row.id}")
    return detail(portal.get_submission(row.id))


def _set_attachment_path(submission_id: int, path: str) -> None:
    from backend.app.db.portal.repository import _connect

    with _connect() as conn:
        conn.execute("UPDATE submissions SET attachment_path = %s WHERE id = %s", (path, submission_id))


def attachment(user: UserRow, submission_id: int) -> tuple[str, bytes]:
    row = portal.get_submission(submission_id)
    if row is None or not (user.role == "reviewer" or row.owner_user_id == user.user_id):
        raise ReviewError(404, "unknown submission")
    if not row.attachment_path or not Path(row.attachment_path).is_file():
        raise ReviewError(404, "this submission has no attachment")
    return row.attachment_name or "attachment.pdf", Path(row.attachment_path).read_bytes()


# ---- review ----

def _get(submission_id: int) -> SubmissionRow:
    row = portal.get_submission(submission_id)
    if row is None:
        raise ReviewError(404, "unknown submission")
    return row


def start(reviewer: UserRow, submission_id: int) -> dict:
    row = portal.update_submission(submission_id, expect_status=("pending", "in_review"),
                                   status="in_review", assignee=reviewer.user_id)
    if row is None:
        _get(submission_id)
        raise ReviewError(409, "this submission was already decided")
    return detail(row)


def approve(reviewer: UserRow, submission_id: int, note: str) -> dict:
    sub = _get(submission_id)
    if sub.status not in ("pending", "in_review"):
        raise ReviewError(409, "this submission was already decided")
    try:
        spec = parse_spec(manifest_to_spec(sub.manifest, sub.service_uuid))
        mapped = map_service(spec)
    except (SpecError, MapError) as exc:
        raise ReviewError(422, f"the manifest can't be turned into tools: {exc}") from None
    holder = registry.find_by_domain(spec.domain)
    if holder and holder.service_uuid != spec.service_uuid:
        raise ReviewError(409, f"{spec.domain} is registered to another service")
    # Into the catalog: from now on users can find, connect and publish it. A new version only
    # updates the spec; the next publish notices the change and regenerates (see publish.py).
    registry.upsert_service(spec)
    registry.upsert_endpoints(spec.service_uuid, mapped)
    pub = sub.manifest.get("publisher") or {}
    registry.upsert_business(spec.service_uuid, pub.get("name") or spec.service_name, [spec.service_name],
                             pub.get("contactEmail"), owner_user_id=sub.owner_user_id)
    row = portal.update_submission(submission_id, expect_status=("pending", "in_review"), status="approved",
                                   reviewed_at=_now(), reviewer=reviewer.user_id, note=(note or "")[:2000])
    if row is None:
        raise ReviewError(409, "this submission was already decided")
    text = f"{row.service_name} {row.version} was approved and is in the Alexa+ catalog."
    notify(row.owner_user_id, "approved", text, f"/owner/{row.service_uuid}")
    owner = portal.get_user(row.owner_user_id) if row.owner_user_id else None
    send_notice_email(pub.get("contactEmail") or (owner.email if owner else None),
                      f"{row.service_name} {row.version} approved",
                      f"{text}\n\nReviewer note: {row.note or '-'}\n")
    return detail(row)


def reject(reviewer: UserRow, submission_id: int, reason: str) -> dict:
    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise ReviewError(422, f"Give the owner a reason of at least {MIN_REASON} characters.")
    _get(submission_id)
    row = portal.update_submission(submission_id, expect_status=("pending", "in_review"), status="rejected",
                                   reviewed_at=_now(), reviewer=reviewer.user_id, reason=reason[:2000])
    if row is None:
        raise ReviewError(409, "this submission was already decided")
    text = f"{row.service_name} {row.version} was rejected: {reason}"
    notify(row.owner_user_id, "rejected", text, f"/owner/{row.service_uuid}")
    owner = portal.get_user(row.owner_user_id) if row.owner_user_id else None
    send_notice_email((row.manifest.get("publisher") or {}).get("contactEmail") or (owner.email if owner else None),
                      f"{row.service_name} {row.version} needs changes", f"{text}\n")
    return detail(row)


def review_catalog() -> list[dict]:
    from backend.app.api.catalog import _connected_users

    out = []
    for row in registry.list_services():
        biz = registry.get_business(row.service_uuid)
        subs = portal.list_submissions(service_uuid=row.service_uuid)
        approved = next((s for s in subs if s.status == "approved"), None)
        out.append({
            "service_uuid": row.service_uuid, "service_name": row.service_name, "domain": row.domain,
            "profile": row.profile or {}, "business": biz.business_name if biz else None,
            "approved_version": approved.version if approved else None,
            "approved_at": approved.reviewed_at if approved else None,
            "published": row.active_version is not None, "bundle_version": row.active_version,
            "published_at": row.published_at, "connected_users": _connected_users(row.service_uuid),
            "tools_count": len(registry.get_endpoints(row.service_uuid)),
        })
    return out


# ---- Try it: the real API with the test account, before anything is published ----

def _test_account_token(sub: SubmissionRow) -> str:
    """Sign the manifest's test account in at the service's OAuth server.

    The demo's fake provider approves straight away using login_hint, so this needs no browser.
    A real provider would need the reviewer to sign in with the test account in a popup.
    """
    s = get_settings()
    linking = sub.manifest.get("accountLinking") or {}
    account = ((sub.manifest.get("private") or {}).get("testAccount") or {}).get("username", "")
    redirect_uri = f"{s.api_url}/oauth/callback"
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        auth = client.get(rewrite(linking.get("authorizationUrl", ""), s.upstream_rewrites), params={
            "client_id": linking.get("clientId") or s.oauth_client_id, "redirect_uri": redirect_uri,
            "response_type": "code", "scope": " ".join(linking.get("scopes") or []),
            "state": "review-try", "login_hint": account.split("@")[0],
        })
        code = parse_qs(urlsplit(auth.headers.get("location", "")).query).get("code", [None])[0]
        if not code:
            raise ReviewError(502, "The service's sign-in page didn't sign the test account in.")
        tok = client.post(rewrite(linking.get("tokenUrl", ""), s.upstream_rewrites), data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": linking.get("clientId") or s.oauth_client_id, "client_secret": s.oauth_client_secret,
        })
        if tok.status_code != 200 or "access_token" not in tok.json():
            raise ReviewError(502, "The service's token endpoint didn't return a token for the test account.")
        return tok.json()["access_token"]


def try_tool(reviewer: UserRow, submission_id: int, tool_name: str, args: dict) -> dict:
    sub = _get(submission_id)
    try:
        spec = parse_spec(manifest_to_spec(sub.manifest, sub.service_uuid))
        mapped = map_service(spec)
    except (SpecError, MapError) as exc:
        raise ReviewError(422, f"the manifest can't be turned into tools: {exc}") from None
    endpoint = next((e for e in mapped.endpoints if e.tool_name == tool_name or e.endpoint_id == tool_name), None)
    if endpoint is None:
        raise ReviewError(404, f"no tool {tool_name}")
    path, query, body = endpoint.path_template, {}, {}
    for p in endpoint.params:
        value = args.get(p.name, args.get(p.wire_name or p.name))
        if value in (None, ""):
            if p.required:
                raise ReviewError(422, f"{p.name} is required")
            continue
        if p.json_type == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ReviewError(422, f"{p.name} must be a whole number") from None
        wire = p.wire_name or p.name
        if p.location == "path":
            path = path.replace("{" + p.name + "}", quote(str(value), safe=""))
        elif p.location == "query":
            query[wire] = value
        elif p.location == "body":
            body[wire] = value
    url = spec.base_url + path
    token = _test_account_token(sub)
    try:
        resp = httpx.request(endpoint.method, rewrite(url, get_settings().upstream_rewrites), params=query or None,
                             json=body or None, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except httpx.HTTPError:
        raise ReviewError(502, f"Couldn't reach {spec.domain}'s API at {spec.base_url}.") from None
    try:
        data = resp.json()
    except ValueError:
        data = {"text": resp.text[:500]}
    is_error = resp.status_code >= 400
    profile_tool = (spec.profile or {}).get("tools", {}).get(endpoint.endpoint_id, {})
    return {
        "tool": endpoint.tool_name, "arguments": {**query, **body} | ({"path": path} if path != endpoint.path_template else {}),
        "request": {"method": endpoint.method, "url": url + (("?" + str(httpx.QueryParams(query))) if query else "")},
        "status": resp.status_code, "is_error": is_error,
        "data": data if isinstance(data, dict) else {"result": data},
        "text": speak(profile_tool, data if isinstance(data, dict) else {}, is_error=is_error,
                      status=resp.status_code, fallback=f"{spec.domain} answered {resp.status_code}."),
        "account": ((sub.manifest.get("private") or {}).get("testAccount") or {}).get("username"),
    }
