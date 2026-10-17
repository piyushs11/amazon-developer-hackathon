"""Mock service catalog: serves spec JSON (C1 shape) on :9200."""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

SPECS_DIR = Path(__file__).parent / "specs"

app = FastAPI(title="Mock Catalog")


def _load_specs() -> dict[str, dict]:
    # Read on every request so spec edits show up without a restart.
    specs = {}
    for path in sorted(SPECS_DIR.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        specs[spec["service_uuid"]] = spec
    return specs


@app.get("/services")
def list_services() -> list[dict]:
    # Specs are served raw (no validation here), so service_name may be absent.
    return [
        {"service_uuid": uuid, "service_name": spec.get("service_name")}
        for uuid, spec in _load_specs().items()
    ]


@app.get("/services/{service_uuid}/spec")
def get_spec(service_uuid: str) -> dict:
    spec = _load_specs().get(service_uuid)
    if spec is None:
        raise HTTPException(status_code=404, detail="service not found")
    return spec
