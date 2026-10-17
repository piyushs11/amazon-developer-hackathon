import time

import jwt
import pytest
from fastapi import HTTPException

from backend.app.auth.identity import PlatformJWTIdentity, issue_user_token
from backend.app.auth.router import user_id_from_username
from backend.app.auth.state import StateError, sign_state, verify_state
from backend.tests.dev3_support import DEMO_USER_TOKEN, JWT_SECRET

identity = PlatformJWTIdentity(JWT_SECRET)


async def test_jwt_roundtrip(dev3_env):
    token = issue_user_token("alice")
    assert await identity.user_from_token(token) == "alice"


async def test_jwt_bad_signature_and_expiry(dev3_env):
    token = issue_user_token("alice")
    other = PlatformJWTIdentity("other-secret-that-is-at-least-32-bytes")
    assert await other.user_from_token(token) is None
    expired = jwt.encode({"sub": "alice", "iss": "mcp-bridge", "exp": int(time.time()) - 5},
                         JWT_SECRET, algorithm="HS256")
    assert await identity.user_from_token(expired) is None
    assert await identity.user_from_token("garbage") is None


async def test_demo_login_issues_token(client):
    resp = await client.post("/auth/demo-login", json={"username": "  Alice "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "alice"
    from backend.app.auth.factory import get_identity

    assert await get_identity().user_from_token(body["user_token"]) == "alice"
    assert await get_identity().user_from_token(DEMO_USER_TOKEN) == "demo-user"


def test_bad_username_rejected():
    with pytest.raises(HTTPException):
        user_id_from_username("../etc")


def test_state_roundtrip_tamper_and_expiry(dev3_env):
    state = sign_state("alice", "svc-1")
    assert verify_state(state) == ("alice", "svc-1")

    payload, sig = state.split(".")
    tampered = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB") + "." + sig
    with pytest.raises(StateError):
        verify_state(tampered)
    with pytest.raises(StateError):
        verify_state("not-a-state")
    with pytest.raises(StateError):
        verify_state(state, max_age=-1)
