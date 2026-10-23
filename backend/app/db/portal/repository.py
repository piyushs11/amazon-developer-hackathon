"""Portal tables: users (demo accounts + roles), submissions (owner -> Amazon review) and
notifications. The only place that runs SQL on them."""
import os
from datetime import datetime
from typing import Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from backend.app.db.registry.repository import DEFAULT_DATABASE_URL

Role = Literal["user", "owner", "reviewer"]
SubmissionStatus = Literal["pending", "in_review", "approved", "rejected"]
OPEN_STATUSES = ("pending", "in_review")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      VARCHAR(64)  PRIMARY KEY,           -- same id as the JWT `sub`
    display_name VARCHAR(255) NOT NULL,
    email        VARCHAR(320) NOT NULL,
    color        VARCHAR(16)  NOT NULL DEFAULT '#4a5568',
    role         VARCHAR(16)  NOT NULL DEFAULT 'user'
                 CHECK (role IN ('user', 'owner', 'reviewer')),
    created_at   TIMESTAMP    NOT NULL DEFAULT now()
);

-- One row per version an owner sends for review. service_uuid is fixed at submission time
-- (the existing service for that domain, or a new uuid) so approval knows what to update.
CREATE TABLE IF NOT EXISTS submissions (
    id              SERIAL       PRIMARY KEY,
    service_uuid    VARCHAR(64)  NOT NULL,
    service_name    VARCHAR(255) NOT NULL,
    domain          VARCHAR(255) NOT NULL,
    owner_user_id   VARCHAR(64),
    version         VARCHAR(32)  NOT NULL,
    status          VARCHAR(16)  NOT NULL
                    CHECK (status IN ('pending', 'in_review', 'approved', 'rejected')),
    manifest        JSONB        NOT NULL,
    check_report    JSONB        NOT NULL,
    message         TEXT         NOT NULL DEFAULT '',
    attachment_name VARCHAR(255),
    attachment_path VARCHAR(500),
    submitted_at    TIMESTAMP    NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMP,
    assignee        VARCHAR(64),
    reviewer        VARCHAR(64),
    reason          TEXT,
    note            TEXT,
    UNIQUE (domain, version)
);
CREATE INDEX IF NOT EXISTS submissions_status ON submissions (status);

CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL       PRIMARY KEY,
    user_id    VARCHAR(64)  NOT NULL,
    kind       VARCHAR(32)  NOT NULL,     -- publish_done, publish_failed, expired, approved, ...
    text       TEXT         NOT NULL,
    link       VARCHAR(255),              -- where the UI should go, e.g. /client/services/{uuid}
    read       BOOLEAN      NOT NULL DEFAULT false,
    created_at TIMESTAMP    NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user ON notifications (user_id, created_at DESC);
"""


class UserRow(BaseModel):
    user_id: str
    display_name: str
    email: str
    color: str
    role: Role
    created_at: datetime | None = None


class SubmissionRow(BaseModel):
    id: int
    service_uuid: str
    service_name: str
    domain: str
    owner_user_id: str | None = None
    version: str
    status: SubmissionStatus
    manifest: dict
    check_report: dict
    message: str = ""
    attachment_name: str | None = None
    attachment_path: str | None = None
    submitted_at: datetime
    reviewed_at: datetime | None = None
    assignee: str | None = None
    reviewer: str | None = None
    reason: str | None = None
    note: str | None = None


class NotificationRow(BaseModel):
    id: int
    user_id: str
    kind: str
    text: str
    link: str | None = None
    read: bool
    created_at: datetime


def _connect() -> psycopg.Connection:
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def create_tables() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)


# ---- users ----

def ensure_user(user_id: str, *, display_name: str | None = None, email: str | None = None,
                color: str | None = None, role: Role = "user") -> UserRow:
    """Create the user if missing (an existing row is never changed) and return it."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, display_name, email, color, role)
            VALUES (%s, %s, %s, COALESCE(%s, '#4a5568'), %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id, display_name or user_id.replace("-", " ").title(),
             email or f"{user_id}@example.com", color, role),
        )
        row = conn.execute("SELECT * FROM users WHERE user_id = %s", (user_id,)).fetchone()
    return UserRow.model_validate(row)


def get_user(user_id: str) -> UserRow | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = %s", (user_id,)).fetchone()
    return UserRow.model_validate(row) if row else None


def list_users(role: Role | None = None) -> list[UserRow]:
    with _connect() as conn:
        if role is None:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at, user_id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM users WHERE role = %s ORDER BY created_at, user_id", (role,)
            ).fetchall()
    return [UserRow.model_validate(r) for r in rows]


# ---- submissions ----

def insert_submission(
    *, service_uuid: str, service_name: str, domain: str, owner_user_id: str | None, version: str,
    manifest: dict, check_report: dict, message: str = "", status: SubmissionStatus = "pending",
    attachment_name: str | None = None, attachment_path: str | None = None,
    submitted_at: datetime | None = None, reviewed_at: datetime | None = None,
    reviewer: str | None = None, reason: str | None = None, note: str | None = None,
) -> SubmissionRow | None:
    """Insert one submission. Returns None if (domain, version) already exists."""
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO submissions
                (service_uuid, service_name, domain, owner_user_id, version, status, manifest,
                 check_report, message, attachment_name, attachment_path, submitted_at,
                 reviewed_at, reviewer, reason, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()), %s, %s, %s, %s)
            ON CONFLICT (domain, version) DO NOTHING
            RETURNING *
            """,
            (service_uuid, service_name, domain, owner_user_id, version, status, Jsonb(manifest),
             Jsonb(check_report), message, attachment_name, attachment_path, submitted_at,
             reviewed_at, reviewer, reason, note),
        ).fetchone()
    return SubmissionRow.model_validate(row) if row else None


def get_submission(submission_id: int) -> SubmissionRow | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE id = %s", (submission_id,)).fetchone()
    return SubmissionRow.model_validate(row) if row else None


def list_submissions(*, status: str | None = None, owner_user_id: str | None = None,
                     domain: str | None = None, service_uuid: str | None = None) -> list[SubmissionRow]:
    where, params = [], []
    for column, value in (("status", status), ("owner_user_id", owner_user_id),
                          ("domain", domain), ("service_uuid", service_uuid)):
        if value is not None:
            where.append(f"{column} = %s")
            params.append(value)
    query = "SELECT * FROM submissions"
    if where:
        query += " WHERE " + " AND ".join(where)
    with _connect() as conn:
        rows = conn.execute(query + " ORDER BY submitted_at DESC, id DESC", params).fetchall()
    return [SubmissionRow.model_validate(r) for r in rows]


def open_submission_for(domain: str) -> SubmissionRow | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE domain = %s AND status = ANY(%s) LIMIT 1",
            (domain, list(OPEN_STATUSES)),
        ).fetchone()
    return SubmissionRow.model_validate(row) if row else None


_UPDATABLE = {"status", "reviewed_at", "assignee", "reviewer", "reason", "note"}


def update_submission(submission_id: int, *, expect_status: tuple[str, ...] | None = None,
                      **fields) -> SubmissionRow | None:
    """Update review fields. With expect_status, only updates when the current status is one
    of them (so two reviewers can't both decide). Returns the new row, or None if not updated."""
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)}")
    sets = ", ".join(f"{k} = %s" for k in fields)
    params = [*fields.values(), submission_id]
    query = f"UPDATE submissions SET {sets} WHERE id = %s"
    if expect_status:
        query += " AND status = ANY(%s)"
        params.append(list(expect_status))
    with _connect() as conn:
        row = conn.execute(query + " RETURNING *", params).fetchone()
    return SubmissionRow.model_validate(row) if row else None


# ---- notifications ----

def add_notification(user_id: str, kind: str, text: str, link: str | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO notifications (user_id, kind, text, link) VALUES (%s, %s, %s, %s)",
            (user_id, kind, text, link),
        )


def list_notifications(user_id: str, limit: int = 30) -> list[NotificationRow]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()
    return [NotificationRow.model_validate(r) for r in rows]


def mark_notifications_read(user_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE notifications SET read = true WHERE user_id = %s AND NOT read", (user_id,))
