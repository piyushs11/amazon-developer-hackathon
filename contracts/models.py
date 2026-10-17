"""Shared models C1–C7. See docs/plan/00-overview-and-contracts.md."""
from typing import Literal

from pydantic import BaseModel



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
# ---- C1: ServiceSpec (catalog -> parser) ----

class ParamSpec(BaseModel):
    name: str  # raw catalog name; the mapper sanitises it
    type: str  # JSON type; unknown values are handled by the mapper
    required: bool
    location: Literal["path", "query", "header", "body"]
    description: str | None = None


class EndpointSpec(BaseModel):
    id: str
    path: str
    method: str
    description: str
    params: list[ParamSpec]


class OAuthConfig(BaseModel):
    auth_url: str
    token_url: str
    scopes: list[str]


class ServiceSpec(BaseModel):
    service_uuid: str
    service_name: str
    domain: str
    base_url: str
    auth_type: str
    oauth: OAuthConfig | None = None
    endpoints: list[EndpointSpec]


# ---- C2: MappedService (mapper -> codegen) ----

class MappedParam(BaseModel):
    name: str  # valid Python identifier, never a keyword
    wire_name: str | None = None  # original catalog name, set only when it differs from name
    python_type: str
    json_type: str
    required: bool
    location: Literal["path", "query", "header", "body"]
    description: str


class MappedEndpoint(BaseModel):
    endpoint_id: str  # original catalog id
    tool_name: str  # valid Python identifier, never a keyword
    method: str
    description: str
    path_template: str  # no base URL; placeholders use param names
    read_only: bool
    params: list[MappedParam]  # required before optional
    input_schema: dict


class MappedService(BaseModel):
    service_uuid: str
    service_name: str
    endpoints: list[MappedEndpoint]
