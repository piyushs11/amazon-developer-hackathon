"""Owner Portal (/api/owner/*) and Amazon Review Console (/api/review/*) routes.

Under /api/ because /owner and /review are the portals' own pages on the same domain (EC2).

Owners submit connector manifests for their own services; reviewers check, try, approve or
reject them. Approval puts the service in the catalog users search (see submissions/review.py).
Needs the Postgres registry; roles come from the `users` table (seeded: demobistro-owner,
lakeside-owner, pinepetal-owner, reviewer).
"""
import asyncio
from functools import partial
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from backend.app.api.deps import require_role
from backend.app.db import portal
from backend.app.db.portal import UserRow
from backend.app.submissions import review
from backend.app.submissions.manifest import run_checks

router = APIRouter(tags=["portal"])
Owner = Annotated[UserRow, Depends(require_role("owner"))]
Reviewer = Annotated[UserRow, Depends(require_role("reviewer"))]
OwnerOrReviewer = Annotated[UserRow, Depends(require_role("owner", "reviewer"))]


async def _run(fn, *args):
    try:
        return await asyncio.to_thread(partial(fn, *args))
    except review.ReviewError as exc:
        raise HTTPException(exc.status, exc.message) from None


class ManifestBody(BaseModel):
    manifest: dict


class Attachment(BaseModel):
    name: str = Field(max_length=200)
    content_base64: str = Field(max_length=8 * 1024 * 1024)


class SubmissionBody(BaseModel):
    manifest: dict
    message: str = Field(default="", max_length=2000)
    attachment: Attachment | None = None


class DecisionBody(BaseModel):
    note: str = Field(default="", max_length=2000)
    reason: str = Field(default="", max_length=2000)


class TryBody(BaseModel):
    tool: str = Field(max_length=100)
    arguments: dict = {}


# ---- Owner Portal ----

@router.get("/api/owner/connectors")
async def owner_connectors(owner: Owner) -> list[dict]:
    return await _run(review.owner_connectors, owner)


@router.get("/api/owner/connectors/{service_uuid}")
async def owner_connector(service_uuid: str, owner: Owner) -> dict:
    return await _run(review.owner_connector, owner, service_uuid)


@router.post("/api/owner/checks")
async def owner_checks(body: ManifestBody, _owner: Owner) -> dict:
    """Run the 8 automated checks on an uploaded manifest (nothing is stored)."""
    return await asyncio.to_thread(run_checks, body.manifest)


@router.post("/api/owner/submissions", status_code=201)
async def owner_submit(body: SubmissionBody, owner: Owner) -> dict:
    attachment = body.attachment.model_dump() if body.attachment else None
    return await _run(review.submit, owner, body.manifest, body.message, attachment)


@router.get("/api/submissions/{submission_id}/attachment")
async def submission_attachment(
    submission_id: int, user: OwnerOrReviewer
) -> Response:
    name, data = await _run(review.attachment, user, submission_id)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


# ---- Review Console ----

@router.get("/api/review/submissions")
async def review_queue(_r: Reviewer, status: str | None = None) -> list[dict]:
    rows = await asyncio.to_thread(portal.list_submissions, status=status)
    return await asyncio.to_thread(lambda: [review.summary(r) for r in rows])


@router.get("/api/review/submissions/{submission_id}")
async def review_detail(submission_id: int, _r: Reviewer) -> dict:
    row = await asyncio.to_thread(portal.get_submission, submission_id)
    if row is None:
        raise HTTPException(404, "unknown submission")
    return await asyncio.to_thread(review.detail, row)


@router.post("/api/review/submissions/{submission_id}/start")
async def review_start(submission_id: int, reviewer: Reviewer) -> dict:
    return await _run(review.start, reviewer, submission_id)


@router.post("/api/review/submissions/{submission_id}/approve")
async def review_approve(submission_id: int, body: DecisionBody,
                         reviewer: Reviewer) -> dict:
    return await _run(review.approve, reviewer, submission_id, body.note)


@router.post("/api/review/submissions/{submission_id}/reject")
async def review_reject(submission_id: int, body: DecisionBody,
                        reviewer: Reviewer) -> dict:
    return await _run(review.reject, reviewer, submission_id, body.reason)


@router.post("/api/review/submissions/{submission_id}/try")
async def review_try(submission_id: int, body: TryBody, reviewer: Reviewer) -> dict:
    """Call one tool against the business's real API with the manifest's test account."""
    return await _run(review.try_tool, reviewer, submission_id, body.tool, body.arguments)


@router.get("/api/review/catalog")
async def review_catalog(_r: Reviewer) -> list[dict]:
    return await _run(review.review_catalog)
