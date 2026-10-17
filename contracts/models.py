"""Shared models C1–C7. See docs/plan/00-overview-and-contracts.md."""
from typing import Literal

from pydantic import BaseModel

# TODO Day 0: ServiceSpec, MappedService, CallContext, ToolResult,
#             DeployRequest, DeployResult, RegisterResult, StepError,
#             GenerationResult, PublishResult


# ---- C4: runtime (gateway -> bundle -> call_api) ----

class CallContext(BaseModel):
    """Built by the gateway for EVERY request. Never cached, never module-level."""
    user_id: str  # from the caller's token (C8)
    service_uuid: str  # from the URL path
    base_url: str  # from the bundle manifest / registry
    request_id: str  # for logs and tracing


class ToolResult(BaseModel):
    text: str  # short, speakable
    data: dict | None = None  # trimmed structured result
    is_error: bool = False


# ---- C5: publish to gateway + register ----

class DeployRequest(BaseModel):
    service_uuid: str
    version: str
    bundle_path: str  # local folder or s3:// path


class DeployResult(BaseModel):
    mcp_url: str  # "{GATEWAY_URL}/mcp/{service_uuid}"
    version: str  # now the active version
    status: Literal["deployed", "failed"]
    error: str | None = None


class RegisterResult(BaseModel):
    addon_id: str
    status: Literal["registered", "mocked", "failed"]
