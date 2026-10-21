"""The "map" step of publish(): put the service's mapped JSON (C2) where generate_service reads it.

    registry (service row + mapped endpoints)  ->  MappedService  ->  storage.write_mapped(uuid)

`generate_service` only READS mapped/mapped.{service_uuid}.json; this is the step that writes it.
publish() runs it right before generating, so the generated bundle always matches what the
registry holds when the service is published (a changed spec shows up after re-seeding).

REGISTRY=postgres -> built from Dev 1's registry: get_service() + get_endpoints(), which the
                     seed script filled after parse_spec() + map_service().
REGISTRY=memory   -> the hand-written fixture contracts/fixtures/mapped.*.json with this uuid
                     (the in-memory registry has no endpoints).
"""
import json
import logging
from pathlib import Path

from backend.app.auth.settings import get_settings
from backend.app.pipeline.models import StepError
from backend.app.storage.add_n_read_mcp_tool import Storage, get_storage
from contracts.models import MappedService

log = logging.getLogger("mcp_bridge.publish")
FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
MAX_MESSAGE = 300


class PrepareError(Exception):
    """The map step failed. `step` is a C6 StepError step ("map" or "store")."""

    def __init__(self, step: str, code: str, message: str):
        super().__init__(message)
        self.step = step
        self.code = code
        self.message = message

    def as_step_error(self) -> StepError:
        return StepError(step=self.step, code=self.code, message=self.message[:MAX_MESSAGE])


def _from_registry(service_uuid: str) -> MappedService:
    from backend.app.db import registry

    try:
        service = registry.get_service(service_uuid)
        endpoints = registry.get_endpoints(service_uuid) if service else []
    except Exception as exc:  # e.g. Postgres unreachable; no stack trace to callers
        raise PrepareError("map", "REGISTRY_ERROR", "could not read the service from the registry") from exc
    if service is None:
        raise PrepareError("map", "SERVICE_NOT_FOUND", f"service {service_uuid} is not in the registry")
    if not endpoints:
        raise PrepareError("map", "NO_ENDPOINTS", f"service {service_uuid} has no mapped endpoints")
    _ensure_business(registry, service_uuid)
    return MappedService(
        service_uuid=service.service_uuid, service_name=service.service_name, endpoints=endpoints
    )


def _ensure_business(registry, service_uuid: str) -> None:
    """Onboard the owner if the `businesses` table has no row for this service yet.

    A placeholder row (name from the service, no email) is enough: failure reports for a tool
    that cannot be onboarded then go to AMAZON_SUPPORT_EMAIL only. Never blocks publishing.
    """
    try:
        if registry.ensure_business(service_uuid):
            log.warning("service_uuid=%s had no business row; created one without an email", service_uuid)
    except Exception as exc:  # noqa: BLE001 - e-mail routing must not stop a publish
        log.warning("business row for %s not ensured: %s", service_uuid, type(exc).__name__)


def _from_fixture(service_uuid: str) -> MappedService:
    for path in sorted(FIXTURES.glob("mapped.*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("service_uuid") == service_uuid:
            return MappedService.model_validate(data)
    raise PrepareError("map", "SERVICE_NOT_FOUND", f"no mapped service known for {service_uuid}")


def prepare_mapped(service_uuid: str, *, storage: Storage | None = None) -> str:
    """Build the mapped service for `service_uuid` and store it. Returns where it was written.

    Blocking (database + storage): publish() runs it in a thread. Raises PrepareError.
    """
    mapped = _from_registry(service_uuid) if get_settings().registry == "postgres" \
        else _from_fixture(service_uuid)
    try:
        # exclude_none: `wire_name` is only present when the catalog name differs (C2)
        data = mapped.model_dump(mode="json", exclude_none=True)
        path = (storage or get_storage()).write_mapped(service_uuid, data)
    except Exception as exc:  # disk / S3 trouble
        raise PrepareError("store", type(exc).__name__, str(exc)[:MAX_MESSAGE]) from exc
    log.info("mapped service_uuid=%s endpoints=%d path=%s", service_uuid, len(mapped.endpoints), path)
    return path
