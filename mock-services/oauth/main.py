"""Fake OAuth provider for Demo Bistro (:9100). Auto-approves every request.

Tokens are self-describing so demo-api (a separate process) can check them:
    access:  demo-access.{account}.{expires_at}.{nonce}
    refresh: demo-refresh.{account}.{nonce}
The account comes from `login_hint` (alice, bob, anything else -> guest), so two
platform users get two different upstream accounts.
"""
import secrets
import time
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse

ACCESS_TTL = 120  # short on purpose, so refresh gets exercised
KNOWN_ACCOUNTS = {"alice", "bob"}

app = FastAPI(title="Fake OAuth")
_codes: dict[str, str] = {}  # code -> account (single process, fine for a mock)


def _account(login_hint: str | None) -> str:
    hint = (login_hint or "").lower()
    return hint if hint in KNOWN_ACCOUNTS else "guest"


def _issue(account: str) -> dict:
    expires_at = int(time.time()) + ACCESS_TTL
    return {
        "access_token": f"demo-access.{account}.{expires_at}.{secrets.token_hex(4)}",
        "refresh_token": f"demo-refresh.{account}.{secrets.token_hex(4)}",
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/authorize")
def authorize(redirect_uri: str, state: str = "", login_hint: str | None = None,
              client_id: str = "", response_type: str = "code", scope: str = ""):
    code = secrets.token_urlsafe(16)
    _codes[code] = _account(login_hint)
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode({'code': code, 'state': state})}")


@app.post("/token")
def token(grant_type: str = Form(...), code: str | None = Form(None),
          refresh_token: str | None = Form(None), redirect_uri: str | None = Form(None),
          client_id: str | None = Form(None), client_secret: str | None = Form(None)) -> dict:
    if grant_type == "authorization_code":
        account = _codes.pop(code or "", None)
        if account is None:
            raise HTTPException(400, {"error": "invalid_grant"})
        return _issue(account)
    if grant_type == "refresh_token":
        parts = (refresh_token or "").split(".")
        if len(parts) != 3 or parts[0] != "demo-refresh":
            raise HTTPException(400, {"error": "invalid_grant"})
        return _issue(parts[1])
    raise HTTPException(400, {"error": "unsupported_grant_type"})
