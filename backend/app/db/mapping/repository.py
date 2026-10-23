"""user_service_mapping: which user connected which service (written at OAuth callback)."""
import os
import threading
from datetime import UTC, datetime
from typing import Literal, Protocol

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

DEFAULT_DATABASE_URL = "postgresql://mcpbridge:mcpbridge@127.0.0.1:5432/mcpbridge"

Status = Literal["active", "expired", "revoked"]


class ConnectionRow(BaseModel):
    user_id: str
    service_uuid: str
    status: Status
    connected_at: datetime
    last_called_at: datetime | None = None
    enabled: bool = True  # the user's on/off switch; off = the gateway refuses calls


class MappingStore(Protocol):
    def upsert_connection(
        self, user_id: str, service_uuid: str, status: Status = "active"
    ) -> None: ...
    def get_connection(self, user_id: str, service_uuid: str) -> ConnectionRow | None: ...
    def list_for_user(self, user_id: str) -> list[ConnectionRow]: ...
    def touch(self, user_id: str, service_uuid: str) -> None: ...
    def set_status(self, user_id: str, service_uuid: str, status: Status) -> bool: ...
    def set_enabled(self, user_id: str, service_uuid: str, enabled: bool) -> bool: ...
    def count_for_service(self, service_uuid: str) -> int: ...


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class InMemoryMappingStore:
    def __init__(self):
        self._rows: dict[tuple[str, str], ConnectionRow] = {}
        self._lock = threading.Lock()

    def upsert_connection(self, user_id: str, service_uuid: str, status: Status = "active") -> None:
        with self._lock:
            old = self._rows.get((user_id, service_uuid))
            self._rows[(user_id, service_uuid)] = ConnectionRow(
                user_id=user_id, service_uuid=service_uuid, status=status,
                connected_at=_now(), last_called_at=old.last_called_at if old else None,
                enabled=old.enabled if old else True,
            )

    def get_connection(self, user_id: str, service_uuid: str) -> ConnectionRow | None:
        return self._rows.get((user_id, service_uuid))

    def list_for_user(self, user_id: str) -> list[ConnectionRow]:
        rows = [r for r in self._rows.values() if r.user_id == user_id]
        return sorted(rows, key=lambda r: r.connected_at)

    def touch(self, user_id: str, service_uuid: str) -> None:
        with self._lock:
            row = self._rows.get((user_id, service_uuid))
            if row:
                self._rows[(user_id, service_uuid)] = row.model_copy(
                    update={"last_called_at": _now()}
                )

    def _update(self, user_id: str, service_uuid: str, **fields) -> bool:
        with self._lock:
            row = self._rows.get((user_id, service_uuid))
            if row is None:
                return False
            self._rows[(user_id, service_uuid)] = row.model_copy(update=fields)
            return True

    def set_status(self, user_id: str, service_uuid: str, status: Status) -> bool:
        # Unlike upsert_connection, keeps connected_at (an expiry is not a new connection).
        return self._update(user_id, service_uuid, status=status)

    def set_enabled(self, user_id: str, service_uuid: str, enabled: bool) -> bool:
        return self._update(user_id, service_uuid, enabled=enabled)

    def count_for_service(self, service_uuid: str) -> int:
        return sum(1 for r in self._rows.values() if r.service_uuid == service_uuid and r.status != "revoked")


class PostgresMappingStore:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS user_service_mapping (
        user_id        VARCHAR(64) NOT NULL,
        service_uuid   VARCHAR(64) NOT NULL,
        status         VARCHAR(16) NOT NULL,
        connected_at   TIMESTAMP   NOT NULL DEFAULT now(),
        last_called_at TIMESTAMP,
        PRIMARY KEY (user_id, service_uuid)
    );
    ALTER TABLE user_service_mapping ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true;
    """

    def __init__(self, database_url: str | None = None):
        self._url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        with self._connect() as conn:
            conn.execute(self.SCHEMA)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._url, row_factory=dict_row, connect_timeout=5)

    def upsert_connection(self, user_id: str, service_uuid: str, status: Status = "active") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_service_mapping (user_id, service_uuid, status)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, service_uuid)
                DO UPDATE SET status = EXCLUDED.status, connected_at = now()
                """,
                (user_id, service_uuid, status),
            )

    def get_connection(self, user_id: str, service_uuid: str) -> ConnectionRow | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_service_mapping WHERE user_id = %s AND service_uuid = %s",
                (user_id, service_uuid),
            ).fetchone()
        return ConnectionRow.model_validate(row) if row else None

    def list_for_user(self, user_id: str) -> list[ConnectionRow]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM user_service_mapping WHERE user_id = %s ORDER BY connected_at",
                (user_id,),
            ).fetchall()
        return [ConnectionRow.model_validate(r) for r in rows]

    def touch(self, user_id: str, service_uuid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE user_service_mapping SET last_called_at = now() "
                "WHERE user_id = %s AND service_uuid = %s",
                (user_id, service_uuid),
            )

    def set_status(self, user_id: str, service_uuid: str, status: Status) -> bool:
        # Unlike upsert_connection, keeps connected_at (an expiry is not a new connection).
        with self._connect() as conn:
            return conn.execute(
                "UPDATE user_service_mapping SET status = %s WHERE user_id = %s AND service_uuid = %s",
                (status, user_id, service_uuid),
            ).rowcount > 0

    def set_enabled(self, user_id: str, service_uuid: str, enabled: bool) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "UPDATE user_service_mapping SET enabled = %s WHERE user_id = %s AND service_uuid = %s",
                (enabled, user_id, service_uuid),
            ).rowcount > 0

    def count_for_service(self, service_uuid: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count(*) AS n FROM user_service_mapping "
                "WHERE service_uuid = %s AND status <> 'revoked'",
                (service_uuid,),
            ).fetchone()
        return row["n"]
