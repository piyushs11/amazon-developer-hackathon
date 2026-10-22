"""REST API (contract C7): find a service, OAuth connect, publish jobs, the user's services.

POST /auth/demo-login lives in backend/app/auth/router.py and POST /mcp/{service_uuid} in the
gateway. Every route here except /oauth/callback takes the user token (`get_current_user`:
bare 401 when it is missing or wrong); the user always comes from the token, never from the body.
"""
import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from backend.app.api import catalog
from backend.app.api.catalog import guess_input
from backend.app.api.jobs import get_jobs
from backend.app.api.schemas import (
    SERVICE_UUID_PATTERN,
    MyService,
    OAuthStartResponse,
    PublishRequest,
    PublishStarted,
    PublishStatus,
    ResolveRequest,
    ServiceDetails,
)
from backend.app.auth.identity import get_current_user
from backend.app.auth.oauth import (
    CallbackResult,
    OAuthError,
    build_auth_url,
    callback_redirect,
    handle_callback,
)
from backend.app.resolver import ResolveResponse, ServiceResolverInput

log = logging.getLogger("mcp_bridge.api")
router = APIRouter(tags=["api"])
_SERVICE_UUID = re.compile(SERVICE_UUID_PATTERN)


# ---- Find a service (S1) ----

@router.post("/resolve-service", response_model=ResolveResponse)
async def resolve_service(
    body: ResolveRequest, _user_id: str = Depends(get_current_user)
) -> ResolveResponse:
    try:
        if body.query is not None:
            query = guess_input(body.query)
        else:
            query = ServiceResolverInput.model_validate(body.model_dump(exclude={"query"}))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0]["msg"]) from None
    try:
        return await asyncio.to_thread(catalog.resolve_service, query)
    except Exception:
        log.exception("resolve-service failed")
        raise HTTPException(503, "could not search services, please try again") from None


@router.get("/services/{service_uuid}", response_model=ServiceDetails)
async def service_details(
    service_uuid: str, _user_id: str = Depends(get_current_user)
) -> ServiceDetails:
    if not _SERVICE_UUID.match(service_uuid):
        raise HTTPException(422, "service_uuid: letters, digits and '-' only")
    try:
        details = await asyncio.to_thread(catalog.service_details, service_uuid)
    except Exception:
        log.exception("services/%s failed", service_uuid)
        raise HTTPException(503, "could not load the service, please try again") from None
    if details is None:
        raise HTTPException(404, "unknown service")
    return details


# ---- OAuth: connect a service ----

@router.get("/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(
    service_uuid: str = Query(...), user_id: str = Depends(get_current_user)
) -> OAuthStartResponse:
    if not _SERVICE_UUID.match(service_uuid):
        raise HTTPException(422, "service_uuid: letters, digits and '-' only")
    try:
        # The service lookup reads the registry (blocking), so keep it off the event loop.
        auth_url = await asyncio.to_thread(build_auth_url, user_id, service_uuid)
    except OAuthError as exc:  # "unknown service" / "service does not use OAuth": safe to show
        raise HTTPException(404 if str(exc) == "unknown service" else 400, str(exc)) from None
    except Exception:
        log.exception("oauth_start failed service_uuid=%s", service_uuid)
        raise HTTPException(503, "could not start the connection, please try again") from None
    return OAuthStartResponse(auth_url=auth_url)


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = "", state: str = "", error: str | None = None
) -> RedirectResponse:
    """The service's sign-in page sends the browser here. Always redirects to the frontend."""
    if error or not code or not state:  # the user denied access, or the call is malformed
        result = CallbackResult(status="error", error=error or "missing code or state")
    else:
        try:
            result = await handle_callback(code, state)
        except Exception:
            log.exception("oauth_callback failed")
            result = CallbackResult(status="error", error="could not save the connection")
    return RedirectResponse(callback_redirect(result), status_code=302)


# ---- Publish ----

@router.post("/publish", response_model=PublishStarted)
async def publish_service(
    body: PublishRequest, user_id: str = Depends(get_current_user)
) -> PublishStarted:
    job = get_jobs().start(user_id, body.service_uuid)
    return PublishStarted(job_id=job.id)


@router.get("/publish/{job_id}", response_model=PublishStatus)
async def publish_status(job_id: str, user_id: str = Depends(get_current_user)) -> PublishStatus:
    job = get_jobs().get(job_id, user_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job.to_status()


# ---- The user's services ----

def _my_services(user_id: str) -> list[MyService]:
    from backend.app.auth.factory import get_mapping, get_service_directory
    from backend.app.deploy import mcp_url
    from backend.app.gateway.bundles import get_registry

    directory, registry = get_service_directory(), get_registry()
    services = []
    for row in get_mapping().list_for_user(user_id):
        info = directory.get(row.service_uuid)
        live = registry.get_active_bundle(row.service_uuid) is not None
        if row.status != "active":
            status = row.status  # expired / revoked: the user has to reconnect
        else:
            status = "active" if live else "connected"
        services.append(MyService(
            service_uuid=row.service_uuid,
            service_name=info.service_name if info else row.service_uuid,
            status=status,
            mcp_url=mcp_url(row.service_uuid) if live else None,
            last_called_at=row.last_called_at,
        ))
    return services


@router.get("/me/services", response_model=list[MyService])
async def my_services(user_id: str = Depends(get_current_user)) -> list[MyService]:
    try:
        return await asyncio.to_thread(_my_services, user_id)
    except Exception:
        log.exception("me/services failed")
        raise HTTPException(503, "could not load your services, please try again") from None


def _disconnect(user_id: str, service_uuid: str) -> bool:
    from backend.app.auth.factory import get_mapping, get_token_store

    mapping = get_mapping()
    connection = mapping.get_connection(user_id, service_uuid)
    if connection is None or connection.status == "revoked":
        return False
    get_token_store().delete(user_id, service_uuid)  # the stored upstream token is gone for good
    mapping.upsert_connection(user_id, service_uuid, "revoked")
    return True


@router.delete("/me/services/{service_uuid}", status_code=204)
async def disconnect(service_uuid: str, user_id: str = Depends(get_current_user)) -> Response:
    """Forget this user's connection. The service stays published for everyone else."""
    if not _SERVICE_UUID.match(service_uuid):
        raise HTTPException(422, "service_uuid: letters, digits and '-' only")
    try:
        found = await asyncio.to_thread(_disconnect, user_id, service_uuid)
    except Exception:
        log.exception("disconnect failed service_uuid=%s", service_uuid)
        raise HTTPException(503, "could not disconnect, please try again") from None
    if not found:
        raise HTTPException(404, "not connected")
    return Response(status_code=204)
