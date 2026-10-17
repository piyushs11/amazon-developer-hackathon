"""Pipeline result models (contract C6).

Defined here exactly as in 00-overview-and-contracts.md until contracts/models.py is filled in;
move them there then (shared contract: all 4 devs approve).
"""

from typing import Literal

from pydantic import BaseModel


class StepError(BaseModel):
    step: Literal["parse", "map", "codegen", "store", "deploy", "register"]
    code: str
    message: str


class GenerationResult(BaseModel):
    service_uuid: str
    status: Literal["ok", "failed"]
    bundle_path: str | None = None
    tools: list[str] = []
    errors: list[StepError] = []
