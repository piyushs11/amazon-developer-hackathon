"""Request and response shapes of the REST API (contract C7)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# A service uuid is used as a storage key and in URLs: letters, digits and dashes only.
SERVICE_UUID_PATTERN = r"^[A-Za-z0-9-]{1,64}$"


class OAuthStartResponse(BaseModel):
    auth_url: str


class PublishRequest(BaseModel):
    service_uuid: str = Field(pattern=SERVICE_UUID_PATTERN)


class PublishStarted(BaseModel):
    job_id: str


class JobError(BaseModel):
    step: str
    code: str
    message: str


class PublishStatus(BaseModel):
    status: Literal["running", "done", "failed"]
    stage: str  # queued | generating | deploying | registering | skipped | done | failed
    mcp_url: str | None = None
    skipped: bool = False  # another user had already published the service
    version: str | None = None
    error: JobError | None = None


class MyService(BaseModel):
    service_uuid: str
    service_name: str
    # connected = signed in but not published yet; active = live; expired/revoked = reconnect
    status: Literal["connected", "active", "expired", "revoked"]
    mcp_url: str | None = None  # the same for every user; only set once the service is published
    last_called_at: datetime | None = None
