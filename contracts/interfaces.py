"""Shared Protocols. See docs/plan/00-overview-and-contracts.md."""
from typing import Protocol

from contracts.models import DeployRequest, DeployResult, RegisterResult

# TODO: Storage (Dev 2)


class TokenProvider(Protocol):  # C4 — Dev 3 implements, runtime/client.py calls
    async def get_valid_token(self, user_id: str, service_uuid: str) -> str: ...


class Deployer(Protocol):  # C5 — validates the bundle loads, then marks it active
    async def deploy(self, req: DeployRequest) -> DeployResult: ...


class Registrar(Protocol):  # C5
    async def register(self, name: str, mcp_url: str, version: str) -> RegisterResult: ...


class IdentityResolver(Protocol):  # C8 — bearer token -> user_id, or None
    async def user_from_token(self, bearer_token: str) -> str | None: ...
