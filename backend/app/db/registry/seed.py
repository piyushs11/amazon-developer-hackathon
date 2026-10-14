"""Seed the registry from the mock catalog: python -m backend.app.db.registry.seed"""
import os

import httpx

from backend.app.db import registry
from backend.app.mapper import MapError, map_service
from backend.app.spec import SpecError, parse_spec

CATALOG_URL = os.getenv("CATALOG_URL", "http://localhost:9200")


def seed() -> None:
    registry.create_tables()
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
            print(f"seeded {uuid}: {spec.service_name} ({len(mapped.endpoints)} endpoints)")


if __name__ == "__main__":
    seed()
