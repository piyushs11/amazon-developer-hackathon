"""C8: who is calling? Bearer token -> user_id.

- PlatformJWTIdentity: user tokens issued by /auth/demo-login (HS256, sub = user_id).
- FixedTokenIdentity: DEMO_USER_TOKEN -> "demo-user" (local fake, for curl / Inspector).
No token or an unknown token -> bare 401 (no WWW-Authenticate header: Alexa+ requirement).
"""
import hmac
import time

import jwt
from fastapi import HTTPException, Request

from backend.app.auth.settings import get_settings

DEMO_USER_ID = "demo-user"
_ISSUER = "mcp-bridge"


class FixedTokenIdentity:
    def __init__(self, token: str | None):
        self._token = token

    async def user_from_token(self, bearer_token: str) -> str | None:
        if self._token and hmac.compare_digest(bearer_token, self._token):
            return DEMO_USER_ID
        return None


class PlatformJWTIdentity:
    def __init__(self, secret: str):
        self._secret = secret

    async def user_from_token(self, bearer_token: str) -> str | None:
        try:
            claims = jwt.decode(
                bearer_token, self._secret, algorithms=["HS256"], issuer=_ISSUER,
                options={"require": ["sub", "exp", "iss"]},
            )
        except jwt.PyJWTError:
            return None
        sub = claims.get("sub")
        return sub if isinstance(sub, str) and sub else None


class ChainIdentity:
    """First resolver that recognises the token wins."""

    def __init__(self, resolvers: list):
        self._resolvers = resolvers

    async def user_from_token(self, bearer_token: str) -> str | None:
        for resolver in self._resolvers:
            user_id = await resolver.user_from_token(bearer_token)
            if user_id:
                return user_id
        return None


def issue_user_token(user_id: str) -> str:
    s = get_settings()
    now = int(time.time())
    claims = {"sub": user_id, "iss": _ISSUER, "iat": now, "exp": now + s.user_token_ttl_seconds}
    return jwt.encode(claims, s.platform_jwt_secret, algorithm="HS256")


def build_identity():
    s = get_settings()
    resolvers = []
    if "jwt" in s.identity:
        resolvers.append(PlatformJWTIdentity(s.platform_jwt_secret))
    if "fixed" in s.identity:
        resolvers.append(FixedTokenIdentity(s.demo_user_token))
    return ChainIdentity(resolvers)


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


class Unauthorized(HTTPException):
    def __init__(self):
        # No headers on purpose: never send WWW-Authenticate.
        super().__init__(status_code=401, detail="unauthorized")


async def get_current_user(request: Request) -> str:
    """FastAPI dependency for every /api route except demo-login and the OAuth callback."""
    from backend.app.auth.factory import get_identity

    token = bearer_token(request)
    user_id = await get_identity().user_from_token(token) if token else None
    if not user_id:
        raise Unauthorized()
    return user_id
