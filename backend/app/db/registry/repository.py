"""Registry repository: the only place that runs SQL on the registry tables."""
import os
from datetime import datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from contracts.models import MappedEndpoint, MappedService, OAuthConfig, ServiceSpec

# Matches docker-compose.yml; override with DATABASE_URL.
# 127.0.0.1, not localhost: on Docker Desktop, localhost tries IPv6 first and that never answers.
DEFAULT_DATABASE_URL = "postgresql://mcpbridge:mcpbridge@127.0.0.1:5432/mcpbridge"

SCHEMA = """
CREATE TABLE IF NOT EXISTS service_registry (
    service_uuid   VARCHAR(64)  PRIMARY KEY,
    service_name   VARCHAR(255) NOT NULL,
    domain         VARCHAR(255) NOT NULL UNIQUE,  -- unique index serves find_by_domain
    base_url       VARCHAR(500) NOT NULL,
    auth_type      VARCHAR(32)  NOT NULL,
    oauth          JSONB,
    -- active bundle
    active_version VARCHAR(64),                   -- NULL until first publish
    bundle_path    VARCHAR(500),                  -- bundles/{uuid}/{version}/ or s3://...
    spec_hash      VARCHAR(64),                   -- lets publish() detect a changed spec
    published_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS endpoint_registry (
    service_uuid  VARCHAR(64)  NOT NULL
                  REFERENCES service_registry (service_uuid) ON DELETE CASCADE,
    endpoint_id   VARCHAR(255) NOT NULL,
    position      INTEGER      NOT NULL,          -- keeps the mapped order
    tool_name     VARCHAR(255) NOT NULL,
    method        VARCHAR(16)  NOT NULL,
    description   TEXT         NOT NULL,
    path_template VARCHAR(500) NOT NULL,
    read_only     BOOLEAN      NOT NULL,
    params        JSONB        NOT NULL,
    input_schema  JSONB        NOT NULL,
    PRIMARY KEY (service_uuid, endpoint_id)
);

-- Who owns a service. The failure e-mail for a tool that could not be onboarded goes to `email`
-- (verifier/utilities.get_business_email reads it by service_uuid).
CREATE TABLE IF NOT EXISTS businesses (
    service_uuid  VARCHAR(64)  PRIMARY KEY
                  REFERENCES service_registry (service_uuid) ON DELETE CASCADE,
    business_name VARCHAR(255) NOT NULL,
    service_names TEXT[]       NOT NULL DEFAULT '{}',
    email         VARCHAR(320),                   -- NULL until the business gives one
    created_at    TIMESTAMP    NOT NULL DEFAULT now()
);

-- Added after the first release: ADD COLUMN IF NOT EXISTS upgrades existing databases in place.
-- profile: display + voice data from the spec/manifest (description, city, phrases, templates).
ALTER TABLE service_registry ADD COLUMN IF NOT EXISTS profile JSONB;
-- The owner account (users.user_id) that manages this business in the Owner Portal.
ALTER TABLE businesses ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(64);
"""


class ServiceRow(BaseModel):
    service_uuid: str
    service_name: str
    domain: str
    base_url: str
    auth_type: str
    oauth: OAuthConfig | None = None
    active_version: str | None = None
    bundle_path: str | None = None
    spec_hash: str | None = None
    published_at: datetime | None = None
    profile: dict | None = None


class BusinessRow(BaseModel):
    service_uuid: str
    business_name: str
    service_names: list[str] = []
    email: str | None = None
    created_at: datetime | None = None
    owner_user_id: str | None = None


class ActiveBundle(BaseModel):
    version: str
    bundle_path: str
    base_url: str


def _connect() -> psycopg.Connection:
    # Read the env on every call so tests can point at another database.
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    # Fail fast instead of hanging when the database is unreachable.
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def create_tables() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)


def upsert_service(spec: ServiceSpec) -> None:
    # Updates spec fields only; the active bundle columns are left as they are.
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO service_registry
                (service_uuid, service_name, domain, base_url, auth_type, oauth, profile)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (service_uuid) DO UPDATE SET
                service_name = EXCLUDED.service_name,
                domain = EXCLUDED.domain,
                base_url = EXCLUDED.base_url,
                auth_type = EXCLUDED.auth_type,
                oauth = EXCLUDED.oauth,
                profile = EXCLUDED.profile
            """,
            (
                spec.service_uuid,
                spec.service_name,
                spec.domain,
                spec.base_url,
                spec.auth_type,
                Jsonb(spec.oauth.model_dump()) if spec.oauth else None,
                Jsonb(spec.profile) if spec.profile is not None else None,
            ),
        )


def upsert_endpoints(service_uuid: str, mapped: MappedService) -> None:
    # Replace the whole set in one transaction, so removed endpoints disappear too.
    with _connect() as conn:
        conn.execute("DELETE FROM endpoint_registry WHERE service_uuid = %s", (service_uuid,))
        for position, endpoint in enumerate(mapped.endpoints):
            conn.execute(
                """
                INSERT INTO endpoint_registry
                    (service_uuid, endpoint_id, position, tool_name, method, description,
                     path_template, read_only, params, input_schema)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    service_uuid,
                    endpoint.endpoint_id,
                    position,
                    endpoint.tool_name,
                    endpoint.method,
                    endpoint.description,
                    endpoint.path_template,
                    endpoint.read_only,
                    Jsonb([p.model_dump() for p in endpoint.params]),
                    Jsonb(endpoint.input_schema),
                ),
            )


def ensure_business(
    service_uuid: str,
    *,
    business_name: str | None = None,
    service_names: list[str] | None = None,
    email: str | None = None,
    owner_user_id: str | None = None,
) -> bool:
    """Create the business row for a service if it has none. Returns True if a row was created.

    An existing row is never touched (so a stored email is never overwritten), except that an
    owner is filled in when the row has none. Missing values come from the service: the name
    defaults to its service_name. The service must already be in the registry; otherwise nothing
    is created and False is returned.
    """
    with _connect() as conn:
        if owner_user_id:
            conn.execute(
                "UPDATE businesses SET owner_user_id = %s WHERE service_uuid = %s AND owner_user_id IS NULL",
                (owner_user_id, service_uuid),
            )
        created = conn.execute(
            """
            INSERT INTO businesses (service_uuid, business_name, service_names, email, owner_user_id)
            SELECT s.service_uuid,
                   COALESCE(%s::varchar, s.service_name),
                   COALESCE(%s::text[], ARRAY[s.service_name]),
                   %s::varchar,
                   %s::varchar
            FROM service_registry s
            WHERE s.service_uuid = %s
            ON CONFLICT (service_uuid) DO NOTHING
            """,
            (business_name, service_names, email, owner_user_id, service_uuid),
        ).rowcount
    return created > 0


def upsert_business(
    service_uuid: str, business_name: str, service_names: list[str], email: str | None,
    owner_user_id: str | None = None,
) -> None:
    """Create or replace a business row (review approval and the seed use this). Raises
    LookupError if the service is not in the registry."""
    with _connect() as conn:
        written = conn.execute(
            """
            INSERT INTO businesses (service_uuid, business_name, service_names, email, owner_user_id)
            SELECT s.service_uuid, %s::varchar, %s::text[], %s::varchar, %s::varchar
            FROM service_registry s WHERE s.service_uuid = %s
            ON CONFLICT (service_uuid) DO UPDATE SET
                business_name = EXCLUDED.business_name,
                service_names = EXCLUDED.service_names,
                email = EXCLUDED.email,
                owner_user_id = COALESCE(EXCLUDED.owner_user_id, businesses.owner_user_id)
            """,
            (business_name, service_names, email, owner_user_id, service_uuid),
        ).rowcount
    if written == 0:
        raise LookupError(f"service '{service_uuid}' is not in the registry")


def get_business(service_uuid: str) -> BusinessRow | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM businesses WHERE service_uuid = %s", (service_uuid,)
        ).fetchone()
    return BusinessRow.model_validate(row) if row else None


def get_service(service_uuid: str) -> ServiceRow | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM service_registry WHERE service_uuid = %s", (service_uuid,)
        ).fetchone()
    return ServiceRow.model_validate(row) if row else None


def get_endpoints(service_uuid: str) -> list[MappedEndpoint]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM endpoint_registry WHERE service_uuid = %s ORDER BY position",
            (service_uuid,),
        ).fetchall()
    return [MappedEndpoint.model_validate(row) for row in rows]


def find_by_domain(domain: str) -> ServiceRow | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM service_registry WHERE domain = %s", (domain,)
        ).fetchone()
    return ServiceRow.model_validate(row) if row else None


def search_by_name(name: str, city: str | None) -> list[ServiceRow]:
    # Every word must appear in the name ("lakeside grill" finds "Lakeside Grill"). The city
    # comes from the service profile; when given it narrows the result.
    words = [w for w in name.split() if w] or [name]
    where = " AND ".join("service_name ILIKE %s" for _ in words)
    params: list = [f"%{w}%" for w in words]
    if city:
        where += " AND profile->>'city' ILIKE %s"
        params.append(city.strip())
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM service_registry WHERE {where} ORDER BY service_name", params
        ).fetchall()
    return [ServiceRow.model_validate(row) for row in rows]


def list_services(listed_only: bool = True) -> list[ServiceRow]:
    """The catalog. Services without a profile are test fixtures (e.g. the hostile specs) and
    are left out unless listed_only=False."""
    query = "SELECT * FROM service_registry"
    if listed_only:
        query += " WHERE profile IS NOT NULL"
    with _connect() as conn:
        rows = conn.execute(query + " ORDER BY service_name").fetchall()
    return [ServiceRow.model_validate(row) for row in rows]


def list_businesses(owner_user_id: str | None = None) -> list[BusinessRow]:
    with _connect() as conn:
        if owner_user_id is None:
            rows = conn.execute("SELECT * FROM businesses ORDER BY business_name").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM businesses WHERE owner_user_id = %s ORDER BY business_name",
                (owner_user_id,),
            ).fetchall()
    return [BusinessRow.model_validate(row) for row in rows]


def current_spec_hash(service_uuid: str) -> str | None:
    """Hash of what generation depends on (base URL + mapped endpoints). Compared with the
    spec_hash stored at deploy time, it tells publish() whether the active bundle is stale."""
    import hashlib
    import json

    service = get_service(service_uuid)
    if service is None:
        return None
    endpoints = [e.model_dump() for e in get_endpoints(service_uuid)]
    blob = json.dumps({"base_url": service.base_url, "endpoints": endpoints}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def get_active_bundle(service_uuid: str) -> ActiveBundle | None:
    # Gateway hot path: one primary-key lookup.
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT active_version AS version, bundle_path, base_url
            FROM service_registry
            WHERE service_uuid = %s AND active_version IS NOT NULL
            """,
            (service_uuid,),
        ).fetchone()
    return ActiveBundle.model_validate(row) if row else None


def set_active_version(service_uuid: str, version: str, bundle_path: str, spec_hash: str) -> None:
    with _connect() as conn:
        updated = conn.execute(
            """
            UPDATE service_registry
            SET active_version = %s, bundle_path = %s, spec_hash = %s, published_at = now()
            WHERE service_uuid = %s
            """,
            (version, bundle_path, spec_hash, service_uuid),
        ).rowcount
    if updated == 0:
        raise LookupError(f"service '{service_uuid}' is not in the registry")
