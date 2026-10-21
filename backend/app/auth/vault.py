"""Token vault: upstream OAuth tokens per (user_id, service_uuid). Never logged.

InMemoryTokenStore      TOKEN_PROVIDER=memory  (tests, no database)
LocalTokenStore         TOKEN_PROVIDER=local   (Postgres, encrypted with TOKEN_ENC_KEY)
SecretsManagerTokenStore + FallbackTokenStore
                        TOKEN_PROVIDER=secrets (AWS Secrets Manager first; Postgres when AWS
                        cannot be reached, see FallbackTokenStore)
"""
import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable

import psycopg
from cryptography.fernet import Fernet, InvalidToken

from runtime.tokens import TokenSet, TokenStore

__all__ = [
    "AwsUnavailable",
    "FallbackTokenStore",
    "InMemoryTokenStore",
    "LocalTokenStore",
    "SecretsManagerTokenStore",
    "TokenSet",
    "TokenStore",
]

log = logging.getLogger("mcp_bridge.auth")

# Same default as Dev 1's registry (127.0.0.1, because Docker Desktop tries IPv6 for localhost).
DEFAULT_DATABASE_URL = "postgresql://mcpbridge:mcpbridge@127.0.0.1:5432/mcpbridge"


class InMemoryTokenStore:
    def __init__(self):
        self._data: dict[tuple[str, str], TokenSet] = {}
        self._lock = threading.Lock()

    def put(self, user_id: str, service_uuid: str, tokens: TokenSet) -> None:
        with self._lock:
            self._data[(user_id, service_uuid)] = tokens

    def get(self, user_id: str, service_uuid: str) -> TokenSet | None:
        return self._data.get((user_id, service_uuid))

    def delete(self, user_id: str, service_uuid: str) -> None:
        with self._lock:
            self._data.pop((user_id, service_uuid), None)


class LocalTokenStore:
    """MODE=local: Postgres rows, token set encrypted with a key derived from TOKEN_ENC_KEY."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS user_tokens (
        user_id      VARCHAR(64) NOT NULL,
        service_uuid VARCHAR(64) NOT NULL,
        ciphertext   BYTEA       NOT NULL,
        updated_at   TIMESTAMP   NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, service_uuid)
    );
    """

    def __init__(self, enc_key: str, database_url: str | None = None):
        key = base64.urlsafe_b64encode(hashlib.sha256(enc_key.encode()).digest())
        self._fernet = Fernet(key)
        self._url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        with self._connect() as conn:
            conn.execute(self.SCHEMA)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url, connect_timeout=5)

    def encrypt(self, tokens: TokenSet) -> bytes:
        return self._fernet.encrypt(tokens.model_dump_json().encode())

    def decrypt(self, blob: bytes) -> TokenSet | None:
        try:
            return TokenSet.model_validate_json(self._fernet.decrypt(bytes(blob)))
        except InvalidToken:  # key rotated: treat as not connected
            return None

    def put(self, user_id: str, service_uuid: str, tokens: TokenSet) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_tokens (user_id, service_uuid, ciphertext) VALUES (%s, %s, %s)
                ON CONFLICT (user_id, service_uuid)
                DO UPDATE SET ciphertext = EXCLUDED.ciphertext, updated_at = now()
                """,
                (user_id, service_uuid, self.encrypt(tokens)),
            )

    def get(self, user_id: str, service_uuid: str) -> TokenSet | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ciphertext FROM user_tokens WHERE user_id = %s AND service_uuid = %s",
                (user_id, service_uuid),
            ).fetchone()
        return self.decrypt(row[0]) if row else None

    def delete(self, user_id: str, service_uuid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM user_tokens WHERE user_id = %s AND service_uuid = %s",
                (user_id, service_uuid),
            )


class AwsUnavailable(Exception):
    """AWS could not serve the request (no credentials/region, no network, access denied,
    throttled, ...). The message is only an error code, never a token."""


_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SERVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SM_EXPECTED = {"ResourceNotFoundException", "ResourceExistsException"}


class SecretsManagerTokenStore:
    """MODE=aws: one Secrets Manager secret per (service, user): `mcp-bridge/{service_uuid}/{user_id}`.

    The secret is JSON: the TokenSet fields plus `token` (the access token), which is the shape
    storage.read_cred_tokens.get_user_token reads. Reads are cached for `cache_ttl` seconds so a
    burst of tool calls costs one AWS request; put/delete drop the cached copy.
    AWS trouble raises AwsUnavailable (wrap this store in FallbackTokenStore to survive it).
    """

    def __init__(self, client=None, *, prefix: str = "mcp-bridge", cache_ttl: float = 30.0,
                 clock: Callable[[], float] = time.monotonic):
        self._client_obj = client
        self._prefix = prefix.strip("/")
        self._ttl = cache_ttl
        self._clock = clock
        self._cache: dict[tuple[str, str], tuple[float, TokenSet]] = {}
        self._lock = threading.Lock()

    def _name(self, user_id: str, service_uuid: str) -> str:
        if not isinstance(user_id, str) or not _USER_ID.match(user_id):
            raise ValueError(f"invalid user id: {user_id!r}")
        if not isinstance(service_uuid, str) or not _SERVICE_ID.match(service_uuid):
            raise ValueError(f"invalid service id: {service_uuid!r}")
        return f"{self._prefix}/{service_uuid}/{user_id}"

    def _client(self):
        with self._lock:
            if self._client_obj is None:
                import boto3
                from botocore.config import Config

                # Short timeouts: a missing AWS must fail fast so the fallback can take over.
                self._client_obj = boto3.client(
                    "secretsmanager",
                    config=Config(connect_timeout=2, read_timeout=3,
                                  retries={"max_attempts": 2, "mode": "standard"}),
                )
            return self._client_obj

    def _call(self, operation: str, **kwargs):
        """Run a Secrets Manager call. Expected 'not found/exists' errors pass through as
        ClientError; everything else from AWS becomes AwsUnavailable."""
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return getattr(self._client(), operation)(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "ClientError")
            if code in _SM_EXPECTED:
                raise
            raise AwsUnavailable(code) from None
        except BotoCoreError as exc:  # no credentials, no region, endpoint unreachable, timeout
            raise AwsUnavailable(type(exc).__name__) from None

    def get(self, user_id: str, service_uuid: str) -> TokenSet | None:
        name = self._name(user_id, service_uuid)
        key = (user_id, service_uuid)
        with self._lock:
            hit = self._cache.get(key)
        if hit and self._clock() < hit[0]:
            return hit[1]
        from botocore.exceptions import ClientError

        try:
            value = self._call("get_secret_value", SecretId=name)["SecretString"]
        except ClientError:  # ResourceNotFoundException: this user never connected
            with self._lock:
                self._cache.pop(key, None)
            return None
        try:
            tokens = TokenSet.model_validate(json.loads(value))
        except ValueError:  # not our JSON: treat as not connected
            return None
        with self._lock:
            self._cache[key] = (self._clock() + self._ttl, tokens)
        return tokens

    def put(self, user_id: str, service_uuid: str, tokens: TokenSet) -> None:
        name = self._name(user_id, service_uuid)
        from botocore.exceptions import ClientError

        secret = json.dumps({**tokens.model_dump(), "token": tokens.access_token})
        try:
            self._call("put_secret_value", SecretId=name, SecretString=secret)
        except ClientError:  # ResourceNotFoundException: first connection, create the secret
            try:
                self._call("create_secret", Name=name, SecretString=secret,
                           Description="MCP Bridge: a user's token for one service")
            except ClientError:  # ResourceExistsException: created meanwhile by another request
                self._call("put_secret_value", SecretId=name, SecretString=secret)
        with self._lock:
            self._cache.pop((user_id, service_uuid), None)

    def delete(self, user_id: str, service_uuid: str) -> None:
        name = self._name(user_id, service_uuid)
        from botocore.exceptions import ClientError

        try:
            # Without force a deleted secret stays "scheduled for deletion" for days and its
            # name cannot be reused, so the user could not reconnect.
            self._call("delete_secret", SecretId=name, ForceDeleteWithoutRecovery=True)
        except ClientError:  # ResourceNotFoundException: already gone
            pass
        with self._lock:
            self._cache.pop((user_id, service_uuid), None)


class FallbackTokenStore:
    """Use `primary` (Secrets Manager); use the `fallback` store (Postgres) when AWS is unavailable.

    - get: primary first; a miss or AWS trouble also checks the fallback, so tokens saved there
      during an outage are still found.
    - put: primary; if AWS is unavailable the token goes to the fallback instead.
    - delete: removed from both.
    After an AWS failure the primary is skipped for `retry_after` seconds, so a machine with no
    AWS access is not slowed down by a failing request on every tool call. The fallback store
    is built on first use (`fallback_factory`), so a healthy AWS never touches Postgres here.
    """

    def __init__(self, primary: TokenStore, fallback_factory: Callable[[], TokenStore], *,
                 retry_after: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self._primary = primary
        self._fallback_factory = fallback_factory
        self._fallback_obj: TokenStore | None = None
        self._retry_after = retry_after
        self._clock = clock
        self._down_until = 0.0
        self._lock = threading.Lock()

    def _fallback(self) -> TokenStore:
        with self._lock:
            if self._fallback_obj is None:
                self._fallback_obj = self._fallback_factory()
            return self._fallback_obj

    def _primary_ready(self) -> bool:
        return self._clock() >= self._down_until

    def _trip(self, exc: AwsUnavailable) -> None:
        if self._primary_ready():
            log.warning("AWS Secrets Manager unavailable (%s); using the Postgres token store "
                        "for the next %.0fs", exc, self._retry_after)
        self._down_until = self._clock() + self._retry_after

    def get(self, user_id: str, service_uuid: str) -> TokenSet | None:
        primary_ok = False
        if self._primary_ready():
            try:
                tokens = self._primary.get(user_id, service_uuid)
                if tokens is not None:
                    return tokens
                primary_ok = True
            except AwsUnavailable as exc:
                self._trip(exc)
        try:
            return self._fallback().get(user_id, service_uuid)
        except Exception:
            if primary_ok:  # AWS answered "no such user"; a broken fallback must not hide that
                log.warning("fallback token store unreadable; treating the user as not connected")
                return None
            raise

    def put(self, user_id: str, service_uuid: str, tokens: TokenSet) -> None:
        if self._primary_ready():
            try:
                self._primary.put(user_id, service_uuid, tokens)
                return
            except AwsUnavailable as exc:
                self._trip(exc)
        self._fallback().put(user_id, service_uuid, tokens)

    def delete(self, user_id: str, service_uuid: str) -> None:
        done = False
        if self._primary_ready():
            try:
                self._primary.delete(user_id, service_uuid)
                done = True
            except AwsUnavailable as exc:
                self._trip(exc)
        try:
            self._fallback().delete(user_id, service_uuid)
        except Exception:
            if not done:
                raise
            log.warning("fallback token store not cleaned on delete")
