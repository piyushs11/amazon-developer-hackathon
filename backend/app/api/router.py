"""REST API (contract C7): OAuth connect, publish jobs, and the user's service list.

POST /auth/demo-login lives in backend/app/auth/router.py and POST /mcp/{service_uuid} in the
gateway. Every route here except /oauth/callback takes the user token (`get_current_user`:
bare 401 when it is missing or wrong); the user always comes from the token, never from the body.
"""
import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from backend.app.api.jobs import get_jobs
from backend.app.api.schemas import (
    SERVICE_UUID_PATTERN,
    MyService,
    OAuthStartResponse,
    PublishRequest,
    PublishStarted,
    PublishStatus,
)
from backend.app.auth.identity import get_current_user
from backend.app.auth.oauth import (
    CallbackResult,
    OAuthError,
    build_auth_url,
    callback_redirect,
    handle_callback,
)

log = logging.getLogger("mcp_bridge.api")
router = APIRouter(tags=["api"])
_SERVICE_UUID = re.compile(SERVICE_UUID_PATTERN)


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
