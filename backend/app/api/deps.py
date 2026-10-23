"""Shared dependencies for the portal routes (owner, review, notifications)."""
import asyncio

from fastapi import Depends, HTTPException

from backend.app.auth.identity import get_current_user
from backend.app.auth.settings import get_settings


def require_postgres() -> None:
    """Portal data lives only in Postgres; with REGISTRY=memory (`make dev`) say so plainly."""
    if get_settings().registry != "postgres":
        raise HTTPException(503, "This needs the Postgres registry: run the Docker stack "
                                 "(docker compose --profile app up) or set REGISTRY=postgres.")


def require_role(*roles: str):
    """Dependency: the signed-in user's row, if their role is one of `roles` (else 403)."""

    async def dependency(user_id: str = Depends(get_current_user), _pg: None = Depends(require_postgres)):
        from backend.app.db import portal

        user = await asyncio.to_thread(portal.get_user, user_id)
        if user is None or user.role not in roles:
            raise HTTPException(403, f"needs a {' or '.join(roles)} account")
        return user

    return dependency
