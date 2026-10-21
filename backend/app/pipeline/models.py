"""Pipeline result models (contract C6).

Defined here exactly as in 00-overview-and-contracts.md until contracts/models.py is filled in;
move them there then (shared contract: all 4 devs approve).
"""

from typing import Literal

from pydantic import BaseModel


class StepError(BaseModel):
    # "connect": publish() found no OAuth connection for this user (added with publish()).
    step: Literal["parse", "map", "codegen", "store", "deploy", "register", "connect"]
    code: str
    message: str


class GenerationResult(BaseModel):
    service_uuid: str
    status: Literal["ok", "failed"]
    bundle_path: str | None = None
    tools: list[str] = []
    errors: list[StepError] = []


class PublishResult(BaseModel):
    status: Literal["done", "failed"]
    mcp_url: str | None = None
    error: StepError | None = None
    skipped: bool = False  # True when another user had already published the service
    version: str | None = None  # the active bundle version ("1", "2", ...)
