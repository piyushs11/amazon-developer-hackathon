"""Token vault: upstream OAuth tokens per (user_id, service_uuid). Never logged."""
import base64
import hashlib
import os
import threading

import psycopg
from cryptography.fernet import Fernet, InvalidToken

from runtime.tokens import TokenSet, TokenStore

__all__ = ["InMemoryTokenStore", "LocalTokenStore", "TokenSet", "TokenStore"]

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
