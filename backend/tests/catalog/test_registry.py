"""Round-trip tests for the registry repository. Need Postgres (make db); skipped without it."""
import json
import os
from pathlib import Path

import psycopg
import pytest

from backend.app.db import registry
from backend.app.db.registry.repository import DEFAULT_DATABASE_URL
from backend.app.mapper import map_service
from backend.app.spec import parse_spec

ROOT = Path(__file__).parents[3]
SPECS_DIR = ROOT / "mock-services" / "catalog" / "specs"
TEST_SCHEMA = "registry_test"


@pytest.fixture
def db(monkeypatch):
    # Run each test in its own schema so the dev data is never touched.
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    try:
        conn = psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("Postgres not reachable")
    conn.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
    conn.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
    monkeypatch.setenv("DATABASE_URL", f"{url}?options=-csearch_path%3D{TEST_SCHEMA}")
    registry.create_tables()
    yield
    conn.execute(f"DROP SCHEMA {TEST_SCHEMA} CASCADE")
    conn.close()


@pytest.fixture
def bistro():
    raw = json.loads((SPECS_DIR / "demo_bistro.json").read_text(encoding="utf-8"))
    return parse_spec(raw)


def test_service_round_trip(db, bistro):
    registry.upsert_service(bistro)
    row = registry.get_service(bistro.service_uuid)
    assert (row.service_name, row.domain, row.base_url) == (
        "Demo Bistro", "demobistro.test", "http://localhost:9000",
    )
    assert row.oauth == bistro.oauth
    assert registry.get_service("no-such-uuid") is None


def test_find_by_domain(db, bistro):
    registry.upsert_service(bistro)
    assert registry.find_by_domain("demobistro.test").service_uuid == bistro.service_uuid
    assert registry.find_by_domain("unknown.test") is None


def test_search_by_name(db, bistro):
    registry.upsert_service(bistro)
    assert [r.service_uuid for r in registry.search_by_name("bistro", None)] == [
        bistro.service_uuid
    ]
    assert registry.search_by_name("pizzeria", None) == []


def test_endpoints_round_trip(db, bistro):
    mapped = map_service(bistro)
    registry.upsert_service(bistro)
    registry.upsert_endpoints(bistro.service_uuid, mapped)
    assert registry.get_endpoints(bistro.service_uuid) == mapped.endpoints


def test_upsert_endpoints_replaces_old_set(db, bistro):
    mapped = map_service(bistro)
    registry.upsert_service(bistro)
    registry.upsert_endpoints(bistro.service_uuid, mapped)
    mapped.endpoints.pop()
    registry.upsert_endpoints(bistro.service_uuid, mapped)
    assert [e.endpoint_id for e in registry.get_endpoints(bistro.service_uuid)] == [
        "search_menu", "get_order_status",
    ]


def test_active_bundle(db, bistro):
    registry.upsert_service(bistro)
    # Never published -> None.
    assert registry.get_active_bundle(bistro.service_uuid) is None

    registry.set_active_version(bistro.service_uuid, "v1", "bundles/1111/v1/", "hash1")
    registry.set_active_version(bistro.service_uuid, "v2", "bundles/1111/v2/", "hash2")
    bundle = registry.get_active_bundle(bistro.service_uuid)
    assert (bundle.version, bundle.bundle_path, bundle.base_url) == (
        "v2", "bundles/1111/v2/", "http://localhost:9000",
    )
    assert registry.get_service(bistro.service_uuid).spec_hash == "hash2"


def test_upsert_service_keeps_active_bundle(db, bistro):
    registry.upsert_service(bistro)
    registry.set_active_version(bistro.service_uuid, "v1", "bundles/1111/v1/", "hash1")
    registry.upsert_service(bistro)
    assert registry.get_active_bundle(bistro.service_uuid).version == "v1"


def test_set_active_version_unknown_service(db):
    with pytest.raises(LookupError):
        registry.set_active_version("no-such-uuid", "v1", "bundles/x/v1/", "hash1")


# ---- businesses (owner of a service; the failure e-mail address lives here) ----

def test_ensure_business_creates_a_placeholder_from_the_service(db, bistro):
    registry.upsert_service(bistro)
    assert registry.get_business(bistro.service_uuid) is None
    assert registry.ensure_business(bistro.service_uuid) is True
    row = registry.get_business(bistro.service_uuid)
    assert (row.business_name, row.service_names, row.email) == ("Demo Bistro", ["Demo Bistro"], None)


def test_ensure_business_never_overwrites_an_existing_row(db, bistro):
    registry.upsert_service(bistro)
    assert registry.ensure_business(
        bistro.service_uuid, business_name="Demo Bistro Pvt Ltd", email="owner@demobistro.example"
    )
    assert registry.ensure_business(bistro.service_uuid, email="other@example.com") is False
    assert registry.get_business(bistro.service_uuid).email == "owner@demobistro.example"


def test_ensure_business_for_unknown_service_creates_nothing(db):
    assert registry.ensure_business("no-such-uuid") is False
    assert registry.get_business("no-such-uuid") is None


def test_upsert_business_replaces_and_rejects_unknown_service(db, bistro):
    registry.upsert_service(bistro)
    registry.ensure_business(bistro.service_uuid, email="old@example.com")
    registry.upsert_business(bistro.service_uuid, "New Name", ["A", "B"], "new@example.com")
    row = registry.get_business(bistro.service_uuid)
    assert (row.business_name, row.service_names, row.email) == ("New Name", ["A", "B"], "new@example.com")
    with pytest.raises(LookupError):
        registry.upsert_business("no-such-uuid", "X", [], None)


def test_deleting_the_service_removes_its_business(db, bistro):
    registry.upsert_service(bistro)
    registry.ensure_business(bistro.service_uuid)
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("DELETE FROM service_registry WHERE service_uuid = %s", (bistro.service_uuid,))
    assert registry.get_business(bistro.service_uuid) is None


def test_failure_email_lookup_reads_the_real_table(db, bistro):
    from backend.app.codegen.verifier.utilities import get_business_email

    registry.upsert_service(bistro)
    registry.ensure_business(bistro.service_uuid, email="owner@demobistro.example")
    url = os.environ["DATABASE_URL"]
    connect = lambda: psycopg.connect(url)
    assert get_business_email(bistro.service_uuid, connect=connect) == "owner@demobistro.example"
    assert get_business_email("22222222-2222-2222-2222-222222222222", connect=connect) is None


def test_seed_businesses_adds_missing_rows_and_keeps_changed_emails(db, bistro, capsys):
    from backend.app.db.registry import seed

    registry.upsert_service(bistro)
    seed.seed_businesses({bistro.service_uuid})
    row = registry.get_business(bistro.service_uuid)
    assert (row.business_name, row.email) == ("Demo Bistro Pvt Ltd", "owner@demobistro.example")

    registry.upsert_business(bistro.service_uuid, "Demo Bistro Pvt Ltd", ["Demo Bistro"], "new@example.com")
    seed.seed_businesses({bistro.service_uuid})  # a re-seed must not undo the change
    assert registry.get_business(bistro.service_uuid).email == "new@example.com"


def test_seed_businesses_skips_services_that_were_not_seeded(db, capsys):
    from backend.app.db.registry import seed

    seed.seed_businesses(set())
    assert "skipped business" in capsys.readouterr().out
