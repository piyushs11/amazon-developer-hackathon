"""Seed Postgres for the demo: python -m backend.app.db.registry.seed

1. registry: every catalog service (spec + profile + mapped endpoints) from the mock catalog
2. users: demo users, business owners and the Amazon reviewer (users_seed.json)
3. businesses: who owns which service (businesses_seed.json)
4. submissions: the review history and the pending Pine & Petal submission (submissions_seed.json)
5. connections: Bob's expired Lakeside Dental sign-in, so the reconnect flow can be shown

Safe to re-run (it runs on every `docker compose up`): it only adds what is missing and never
overwrites data created while using the app. Catalog spec fields are refreshed from the catalog.
"""
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from backend.app.db import portal, registry
from backend.app.mapper import MapError, map_service
from backend.app.spec import SpecError, parse_spec

CATALOG_URL = os.getenv("CATALOG_URL", "http://localhost:9200")
HERE = Path(__file__).parent
BUSINESSES_FILE = Path(os.getenv("BUSINESSES_SEED_FILE", HERE / "businesses_seed.json"))
USERS_FILE = HERE / "users_seed.json"
SUBMISSIONS_FILE = HERE / "submissions_seed.json"
MANIFESTS_DIR = HERE / "manifests"


def _days_ago(days: float | None) -> datetime | None:
    if days is None:
        return None
    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)


def seed_businesses(seeded_uuids: set[str]) -> None:
    """Add the owner rows from businesses_seed.json for services that are now in the registry.

    A row that already exists is left alone, so an email a business has since changed is never
    overwritten by a re-seed. Services not seeded here get a placeholder row at publish time.
    """
    if not BUSINESSES_FILE.is_file():
        return
    for item in json.loads(BUSINESSES_FILE.read_text(encoding="utf-8")):
        uuid = item["service_uuid"]
        if uuid not in seeded_uuids:
            print(f"skipped business for {uuid}: service is not in the registry")
            continue
        created = registry.ensure_business(
            uuid,
            business_name=item.get("business_name"),
            service_names=item.get("service_names"),
            email=item.get("email"),
            owner_user_id=item.get("owner_user_id"),
        )
        print(f"{'added' if created else 'kept'} business for {uuid}: {item.get('business_name')}")


def seed_users() -> None:
    if not USERS_FILE.is_file():
        return
    data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    for u in data.get("users", []):
        portal.ensure_user(u["user_id"], display_name=u["display_name"], email=u["email"],
                           color=u.get("color"), role=u.get("role", "user"))
    print(f"users: {', '.join(u['user_id'] for u in data.get('users', []))}")


def seed_connections() -> None:
    from backend.app.db.mapping.repository import PostgresMappingStore

    data = json.loads(USERS_FILE.read_text(encoding="utf-8")) if USERS_FILE.is_file() else {}
    mapping = PostgresMappingStore()  # creates user_service_mapping if the app hasn't yet
    for c in data.get("connections", []):
        if registry.get_service(c["service_uuid"]) is None:
            continue
        if mapping.get_connection(c["user_id"], c["service_uuid"]) is None:
            mapping.upsert_connection(c["user_id"], c["service_uuid"], c.get("status", "active"))
            print(f"connection {c['user_id']} -> {c['service_uuid']}: {c.get('status')}")


def seed_submissions(catalog_specs: dict[str, dict]) -> None:
    from backend.app.submissions import run_checks, service_uuid_for, spec_to_manifest

    if not SUBMISSIONS_FILE.is_file():
        return
    for item in json.loads(SUBMISSIONS_FILE.read_text(encoding="utf-8")):
        owner = portal.get_user(item["owner_user_id"]) if item.get("owner_user_id") else None
        if "from_catalog" in item:
            spec = catalog_specs.get(item["from_catalog"])
            if spec is None:
                continue
            username = "reviewer@" + spec["domain"]
            manifest = spec_to_manifest(spec, item["version"], owner_email=owner.email if owner else "",
                                        test_account={"username": username, "password": "demo-test-account"})
            if item.get("without_confirmation"):  # an early version that was rejected for this
                for ops in manifest["openapi"]["paths"].values():
                    for op in ops.values():
                        op["x-alexa"].pop("confirmationPrompt", None)
                        op["x-alexa"]["requiresConfirmation"] = False
        else:
            manifest = json.loads((MANIFESTS_DIR / item["manifest_file"]).read_text(encoding="utf-8"))
        pub = manifest["publisher"]
        domain = pub["domain"].lower()
        version = item.get("version") or manifest["openapi"]["info"]["version"]
        row = portal.insert_submission(
            service_uuid=item.get("from_catalog") or service_uuid_for(domain),
            service_name=pub["name"], domain=domain, owner_user_id=item.get("owner_user_id"),
            version=version, manifest=manifest, check_report=run_checks(manifest),
            message=item.get("message", ""), status=item["status"],
            attachment_name=item.get("attachment_name"),
            submitted_at=_days_ago(item.get("days_ago")), reviewed_at=_days_ago(item.get("reviewed_days_ago")),
            reviewer="reviewer" if item.get("reviewed_days_ago") is not None else None,
            reason=item.get("reason"), note=item.get("note"),
        )
        if row is None:
            continue  # already seeded
        print(f"submission {domain} {version}: {item['status']}")
        if row.owner_user_id and row.status in ("approved", "rejected"):
            text = (f"{row.service_name} {row.version} was approved and is in the Alexa+ catalog."
                    if row.status == "approved" else
                    f"{row.service_name} {row.version} was rejected: {row.reason}")
            portal.add_notification(row.owner_user_id, row.status, text, f"/owner/{row.service_uuid}")


def seed() -> None:
    registry.create_tables()
    portal.create_tables()
    seeded: set[str] = set()
    catalog_specs: dict[str, dict] = {}
    with httpx.Client(base_url=CATALOG_URL) as catalog:
        for service in catalog.get("/services").raise_for_status().json():
            uuid = service["service_uuid"]
            raw = catalog.get(f"/services/{uuid}/spec").raise_for_status().json()
            try:
                spec = parse_spec(raw)
                mapped = map_service(spec)
            except (SpecError, MapError) as exc:
                # One bad service must not stop the rest.
                print(f"skipped {uuid}: {exc}")
                continue
            registry.upsert_service(spec)
            registry.upsert_endpoints(uuid, mapped)
            seeded.add(uuid)
            catalog_specs[uuid] = raw
            print(f"seeded {uuid}: {spec.service_name} ({len(mapped.endpoints)} endpoints)")
    seed_users()
    seed_businesses(seeded)
    seed_submissions(catalog_specs)
    seed_connections()


if __name__ == "__main__":
    seed()
