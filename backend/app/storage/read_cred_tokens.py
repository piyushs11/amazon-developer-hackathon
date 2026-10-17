"""Read credentials from the auth vault.

Dev tokens are the dummy/temporary logins a service provider creates for their service so
generated tools can be verified before any real user connects. They are keyed
`{service_name}_dev`, apart from the regular per-user tokens (TokenProvider, C4).
"""

import json
import os
import re
from pathlib import Path

DEV_SUFFIX = "_dev"
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def dev_key(service_name: str) -> str:
    if not _IDENT.match(service_name):
        raise ValueError(f"invalid service name: {service_name!r}")
    return f"{service_name}{DEV_SUFFIX}"


def _from_env(key: str) -> str | None:
    return os.environ.get(f"{key.upper()}_TOKEN") or None


def _from_file(key: str) -> str | None:
    root = Path(os.environ.get("GENERATED_DIR", "generated"))
    path = root / "creds" / f"{key}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text()).get("token") or None


def _from_secrets_manager(key: str, client=None) -> str | None:
    if client is None:
        import boto3

        client = boto3.client("secretsmanager")
    try:
        value = client.get_secret_value(SecretId=key)["SecretString"]
    except client.exceptions.ResourceNotFoundException:
        return None
    try:
        return json.loads(value).get("token") or None
    except (ValueError, AttributeError):
        return value or None


_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SERVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")  # a service name or a service uuid


def get_user_token(user_id: str, service_id: str, *, secrets_client=None) -> str | None:
    """Return the token this user connected for a service, or None if not connected.

    `service_id` is just a storage key: the runtime path (call_api) passes the service uuid,
    the verification path (run_tool_call) passes the service name.
    Local: $GENERATED_DIR/creds/users/{service_id}/{user_id}.json -> {"token": ...}
    MODE=aws: Secrets Manager secret `mcp-bridge/{service_id}/{user_id}`.
    Never returns the service's `_dev` token.
    """
    if not isinstance(user_id, str) or not _USER_ID.match(user_id):
        raise ValueError(f"invalid user id: {user_id!r}")
    if not isinstance(service_id, str) or not _SERVICE_ID.match(service_id):
        raise ValueError(f"invalid service id: {service_id!r}")
    if os.environ.get("MODE", "local") == "aws":
        return _from_secrets_manager(f"mcp-bridge/{service_id}/{user_id}", secrets_client)
    root = Path(os.environ.get("GENERATED_DIR", "generated"))
    path = root / "creds" / "users" / service_id / f"{user_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text()).get("token") or None


def get_dev_token(service_name: str, *, secrets_client=None) -> str | None:
    """Return the `_dev` token for `service_name`, or None if none is stored."""
    key = dev_key(service_name)
    if os.environ.get("MODE", "local") == "aws":
        return _from_secrets_manager(key, secrets_client)
    return _from_env(key) or _from_file(key)
