"""Shared models C1–C7. See docs/plan/00-overview-and-contracts.md."""
from typing import Literal

from pydantic import BaseModel

# TODO Day 0: CallContext, ToolResult,
#             DeployRequest, DeployResult, RegisterResult, StepError,
#             GenerationResult, PublishResult


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
