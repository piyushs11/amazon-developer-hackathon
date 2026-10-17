"""Signed, short-lived OAuth `state`: carries user_id + service_uuid through the redirect."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from backend.app.auth.settings import get_settings

STATE_MAX_AGE_SECONDS = 600


class StateError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> bytes:
    key = get_settings().oauth_state_secret.encode()
    return hmac.new(key, payload, hashlib.sha256).digest()


def sign_state(user_id: str, service_uuid: str) -> str:
    payload = json.dumps(
        {"u": user_id, "s": service_uuid, "t": int(time.time()), "n": secrets.token_hex(8)},
        separators=(",", ":"),
    ).encode()
    return f"{_b64(payload)}.{_b64(_sign(payload))}"


def verify_state(state: str, max_age: int = STATE_MAX_AGE_SECONDS) -> tuple[str, str]:
    try:
        payload_b64, sig_b64 = state.split(".")
        payload, sig = _unb64(payload_b64), _unb64(sig_b64)
    except ValueError as exc:
        raise StateError("malformed state") from exc
    if not hmac.compare_digest(sig, _sign(payload)):
        raise StateError("bad state signature")
    data = json.loads(payload)
    if time.time() - data["t"] > max_age:
        raise StateError("state expired")
    return data["u"], data["s"]
