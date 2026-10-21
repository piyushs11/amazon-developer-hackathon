"""Seed the registry from the mock catalog: python -m backend.app.db.registry.seed"""
import json
import os
from pathlib import Path

import httpx

from backend.app.db import registry
from backend.app.mapper import MapError, map_service
from backend.app.spec import SpecError, parse_spec

CATALOG_URL = os.getenv("CATALOG_URL", "http://localhost:9200")
BUSINESSES_FILE = Path(os.getenv("BUSINESSES_SEED_FILE", Path(__file__).with_name("businesses_seed.json")))


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
        )
        print(f"{'added' if created else 'kept'} business for {uuid}: {item.get('business_name')}")


def seed() -> None:
    registry.create_tables()
    seeded: set[str] = set()
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
            print(f"seeded {uuid}: {spec.service_name} ({len(mapped.endpoints)} endpoints)")
    seed_businesses(seeded)


if __name__ == "__main__":
    seed()
