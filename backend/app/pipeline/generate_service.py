"""generate_service(service_uuid): load the stored mapped JSON, onboard it, report (contract C6).

    load_mapped_service(uuid)  -> StepError "map" on failure
    onboard(mapped)            -> "codegen" (generate / seed / verify) or "store" on failure
    GenerationResult           -> ok only if every tool verified; otherwise failed, with the
                                  verified tools still stored as a partial bundle
"""

import tempfile
from contextlib import nullcontext

from backend.app.codegen.verifier.utilities import MappedServiceError, load_mapped_service
from backend.app.pipeline.flow_onboard import MAX_MESSAGE, OnboardStepError, onboard
from backend.app.pipeline.models import GenerationResult, StepError
from backend.app.storage.add_n_read_mcp_tool import Storage, get_storage
from backend.app.storage.tool_cache import ToolCache


def _failed(service_uuid: str, error: StepError, **fields) -> GenerationResult:
    return GenerationResult(service_uuid=service_uuid, status="failed", errors=[error], **fields)


async def generate_service(
    service_uuid: str, *, cache: ToolCache | None = None, storage: Storage | None = None,
    out_dir: str | None = None, **verify_kwargs,
) -> GenerationResult:
    """Generate, verify and store the tool bundle for `service_uuid`. Never raises."""
    try:
        storage = storage or get_storage()
        mapped = load_mapped_service(service_uuid, storage)
    except MappedServiceError as e:
        return _failed(service_uuid, StepError(step="map", code=e.code, message=e.message))
    except Exception as e:  # noqa: BLE001 - e.g. storage unreachable; no stack trace to callers
        return _failed(service_uuid, StepError(step="map", code=type(e).__name__, message=str(e)[:MAX_MESSAGE]))

    folder = nullcontext(out_dir) if out_dir else tempfile.TemporaryDirectory()
    with folder as work_dir:
        try:
            result = await onboard(mapped, work_dir, cache=cache, storage=storage, **verify_kwargs)
        except OnboardStepError as e:
            return _failed(service_uuid, StepError(step=e.step, code=e.code, message=e.message))
        except Exception as e:  # noqa: BLE001
            return _failed(
                service_uuid, StepError(step="codegen", code=type(e).__name__, message=str(e)[:MAX_MESSAGE])
            )

    errors = [
        StepError(step="codegen", code="tool_not_verified", message=f"{tool}: {result['results'][tool]['detail']}"[:MAX_MESSAGE])
        for tool in result["skipped"]
    ]
    return GenerationResult(
        service_uuid=service_uuid,
        status=result["status"],
        bundle_path=result["bundle_path"],
        tools=result["stored"],
        errors=errors,
    )
