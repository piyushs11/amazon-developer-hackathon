"""Step 1: validate a raw catalog spec and return a ServiceSpec (C1)."""
from pydantic import ValidationError

from contracts.models import ServiceSpec

SUPPORTED_AUTH_TYPES = {"oauth2"}
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class SpecError(Exception):
    """One spec problem. `errors` lists every problem found in the same spec."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.errors: list[SpecError] = [self]


def _combined(errors: list[SpecError]) -> SpecError:
    # Raise the first error, carrying all of them for the caller to report.
    first = errors[0]
    first.errors = errors
    return first


def _structural_error(err: dict) -> SpecError:
    # Map a pydantic error to our codes by where in the spec it occurred.
    loc = err["loc"]
    if "params" in loc[:-1]:
        code = "SPEC_BAD_PARAM"
    elif loc and loc[0] == "oauth":
        code = "SPEC_BAD_AUTH"
    else:
        code = "SPEC_MISSING_FIELD"
    return SpecError(code, f"{'.'.join(map(str, loc))}: {err['msg']}")


def _semantic_errors(spec: ServiceSpec) -> list[SpecError]:
    errors = []
    if not spec.endpoints:
        errors.append(SpecError("SPEC_NO_ENDPOINTS", "spec has no endpoints"))

    if spec.auth_type not in SUPPORTED_AUTH_TYPES:
        errors.append(SpecError("SPEC_BAD_AUTH", f"unsupported auth_type '{spec.auth_type}'"))
    elif spec.oauth is None:
        errors.append(SpecError("SPEC_BAD_AUTH", "auth_type 'oauth2' needs an oauth block"))

    seen_ids = set()
    for endpoint in spec.endpoints:
        if endpoint.method not in ALLOWED_METHODS:
            errors.append(SpecError(
                "SPEC_BAD_METHOD", f"endpoint '{endpoint.id}': bad method '{endpoint.method}'"
            ))
        if endpoint.id in seen_ids:
            errors.append(SpecError("SPEC_DUPLICATE_ID", f"duplicate endpoint id '{endpoint.id}'"))
        seen_ids.add(endpoint.id)
    return errors


def parse_spec(raw: dict) -> ServiceSpec:
    # Shape first (missing or wrong-typed fields), then the rules that need a well-formed spec.
    try:
        spec = ServiceSpec.model_validate(raw)
    except ValidationError as exc:
        raise _combined([_structural_error(e) for e in exc.errors()]) from None

    errors = _semantic_errors(spec)
    if errors:
        raise _combined(errors)
    return spec
