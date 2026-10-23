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


class ResolveRequest(BaseModel):
    """C7: {input_type, webpage_url?, name_location?}, or just {query} with whatever was typed."""
    input_type: Literal["url", "name_location"] | None = None
    webpage_url: str | None = Field(default=None, max_length=2048)
    name_location: dict | None = None
    query: str | None = Field(default=None, max_length=2048)


class ServiceTool(BaseModel):
    name: str
    description: str
    read_only: bool


class ServiceDetails(BaseModel):
    service_uuid: str
    service_name: str
    domain: str
    published: bool  # has an active bundle (the same for every user)
    version: str | None = None
    mcp_url: str | None = None
    tools: list[ServiceTool] = []
    # Display + voice data from the spec/manifest (description, city, phrases, scope labels,
    # per-tool titles, confirmation prompts and answer templates). See ServiceSpec.profile.
    profile: dict = {}
    scopes: list[str] = []
    published_at: datetime | None = None
    connected_users: int = 0
    # A newer approved version than the active bundle: the next publish regenerates it.
    update_available: bool = False


class ServiceSummary(BaseModel):
    """One entry of GET /services (the catalog)."""
    service_uuid: str
    service_name: str
    domain: str
    published: bool
    profile: dict = {}


class MyService(BaseModel):
    service_uuid: str
    service_name: str
    # connected = signed in but not published yet; active = live; expired/revoked = reconnect
    status: Literal["connected", "active", "expired", "revoked"]
    mcp_url: str | None = None  # the same for every user; only set once the service is published
    last_called_at: datetime | None = None
    connected_at: datetime | None = None
    enabled: bool = True  # the user's on/off switch (PATCH /me/services/{uuid})
    domain: str = ""
    profile: dict = {}
    update_available: bool = False


class ServiceSwitch(BaseModel):
    enabled: bool


class Notification(BaseModel):
    id: int
    kind: str
    text: str
    link: str | None = None
    read: bool
    created_at: datetime
