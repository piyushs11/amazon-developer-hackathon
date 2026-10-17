"""POST /auth/demo-login (C8). Hackathon auth: username only, no password."""
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.auth.identity import issue_user_token

router = APIRouter(tags=["auth"])

_USER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class DemoLoginRequest(BaseModel):
    username: str


class DemoLoginResponse(BaseModel):
    user_id: str
    user_token: str


def user_id_from_username(username: str) -> str:
    user_id = re.sub(r"\s+", "-", username.strip().lower())
    if not _USER_ID.match(user_id):
        raise HTTPException(422, "username: 1-32 letters, digits, '-' or '_'")
    return user_id


@router.post("/auth/demo-login", response_model=DemoLoginResponse)
def demo_login(req: DemoLoginRequest) -> DemoLoginResponse:
    user_id = user_id_from_username(req.username)
    return DemoLoginResponse(user_id=user_id, user_token=issue_user_token(user_id))
