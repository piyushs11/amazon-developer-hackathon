"""POST /auth/demo-login (C8). Hackathon auth: username only, no password.

With the Postgres registry, users live in the `users` table (seeded with the demo users, the
business owners and the reviewer); a new username is added as a plain user on first login.
"""
import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.auth.identity import get_current_user, issue_user_token
from backend.app.auth.settings import get_settings

router = APIRouter(tags=["auth"])

_USER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class DemoLoginRequest(BaseModel):
    username: str


class UserProfile(BaseModel):
    user_id: str
    display_name: str
    email: str
    color: str = "#4a5568"
    role: str = "user"  # user | owner | reviewer


class DemoLoginResponse(UserProfile):
    user_token: str


def user_id_from_username(username: str) -> str:
    user_id = re.sub(r"\s+", "-", username.strip().lower())
    if not _USER_ID.match(user_id):
        raise HTTPException(422, "username: 1-32 letters, digits, '-' or '_'")
    return user_id


def _profile(user_id: str) -> UserProfile:
    """The user's row (created on first login), or a stand-in without Postgres (`make dev`)."""
    if get_settings().registry != "postgres":
        return UserProfile(user_id=user_id, display_name=user_id.replace("-", " ").title(),
                           email=f"{user_id}@example.com")
    from backend.app.db import portal

    row = portal.ensure_user(user_id)
    return UserProfile.model_validate(row.model_dump())


@router.post("/auth/demo-login", response_model=DemoLoginResponse)
async def demo_login(req: DemoLoginRequest) -> DemoLoginResponse:
    user_id = user_id_from_username(req.username)
    try:
        profile = await asyncio.to_thread(_profile, user_id)
    except Exception:  # noqa: BLE001 - Postgres down: a clean 503, never a stack trace
        raise HTTPException(503, "could not sign in, please try again") from None
    return DemoLoginResponse(**profile.model_dump(), user_token=issue_user_token(user_id))


@router.get("/auth/demo-users", response_model=list[UserProfile])
async def demo_users(role: str = "user") -> list[UserProfile]:
    """Accounts to offer on a sign-in screen (no password in the demo). role: user|owner|reviewer."""
    if get_settings().registry != "postgres":
        return []
    from backend.app.db import portal

    if role not in ("user", "owner", "reviewer"):
        raise HTTPException(422, "role: user, owner or reviewer")
    rows = await asyncio.to_thread(portal.list_users, role)
    return [UserProfile.model_validate(r.model_dump()) for r in rows]


@router.get("/me", response_model=UserProfile)
async def me(user_id: str = Depends(get_current_user)) -> UserProfile:
    return await asyncio.to_thread(_profile, user_id)
