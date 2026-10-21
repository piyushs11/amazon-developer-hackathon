"""Dev 3 settings, read from the environment on every call (tests can monkeypatch).

Can move into backend/app/core/config.py once Dev 4 fills it in.
"""
import os
from dataclasses import dataclass

_DEV_DEFAULT = "change-me-local-only"


@dataclass(frozen=True)
class Settings:
    mode: str
    gateway_url: str
    api_url: str
    frontend_url: str
    token_provider: str  # fake | memory | local | secrets
    registry: str  # memory | postgres
    identity: tuple[str, ...]  # any of: jwt, fixed
    platform_jwt_secret: str
    user_token_ttl_seconds: int
    demo_user_token: str | None
    oauth_state_secret: str
    token_enc_key: str
    oauth_client_id: str
    oauth_client_secret: str
    upstream_rewrites: dict[str, str]  # server-side URL prefixes, e.g. localhost:9000 -> demo-api:9000
    authorize_rewrites: dict[str, str]  # browser-facing authorize URL prefixes


def _rewrites(raw: str) -> dict[str, str]:
    # "http://localhost:9000=http://demo-api:9000,http://localhost:9100=http://oauth:9100"
    pairs = [item.split("=", 1) for item in raw.split(",") if "=" in item]
    return {src.strip(): dst.strip() for src, dst in pairs}


def get_settings() -> Settings:
    mode = os.getenv("MODE", "local")
    s = Settings(
        mode=mode,
        gateway_url=os.getenv("GATEWAY_URL", "http://localhost:8000").rstrip("/"),
        api_url=os.getenv("API_URL", "http://localhost:8000").rstrip("/"),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/"),
        token_provider=os.getenv("TOKEN_PROVIDER", "fake"),
        registry=os.getenv("REGISTRY", "memory"),
        identity=tuple(
            x.strip()
            for x in os.getenv("IDENTITY", "jwt" if mode == "aws" else "jwt,fixed").split(",")
            if x.strip()
        ),
        platform_jwt_secret=os.getenv("PLATFORM_JWT_SECRET", _DEV_DEFAULT),
        user_token_ttl_seconds=int(os.getenv("USER_TOKEN_TTL_SECONDS", str(24 * 3600))),
        demo_user_token=os.getenv("DEMO_USER_TOKEN") or None,
        oauth_state_secret=os.getenv("OAUTH_STATE_SECRET", _DEV_DEFAULT),
        token_enc_key=os.getenv("TOKEN_ENC_KEY", _DEV_DEFAULT),
        oauth_client_id=os.getenv("OAUTH_CLIENT_ID", "mcp-bridge"),
        oauth_client_secret=os.getenv("OAUTH_CLIENT_SECRET", "mcp-bridge-secret"),
        upstream_rewrites=_rewrites(os.getenv("UPSTREAM_REWRITES", "")),
        authorize_rewrites=_rewrites(os.getenv("AUTHORIZE_REWRITES", "")),
    )
    if mode == "aws":
        for name in ("platform_jwt_secret", "oauth_state_secret", "token_enc_key"):
            if getattr(s, name) == _DEV_DEFAULT:
                raise RuntimeError(f"{name.upper()} must be set when MODE=aws")
    return s


def rewrite(url: str, rules: dict[str, str]) -> str:
    for src, dst in rules.items():
        if url.startswith(src):
            return dst + url[len(src):]
    return url
