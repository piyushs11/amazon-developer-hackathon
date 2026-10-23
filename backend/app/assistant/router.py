"""POST /assistant/ask: one turn of Ask mode for the signed-in user (see engine.py).

The client keeps the conversation state and sends it back each turn: `pending` (an action
waiting for yes/no) and `memory` (ids from earlier answers, e.g. the order just placed).
"""
import asyncio
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.assistant import engine
from backend.app.auth.identity import get_current_user

router = APIRouter(tags=["assistant"])


class AskBody(BaseModel):
    text: str = Field(max_length=500)
    pending: dict | None = None
    memory: dict = {}


def _access_for(user_id: str):
    from backend.app.auth.factory import get_mapping
    from backend.app.gateway.bundles import get_registry

    mapping, registry, cache = get_mapping(), get_registry(), {}

    def access(service: engine.ServiceInfo) -> engine.Access:
        if service.uuid not in cache:
            conn = mapping.get_connection(user_id, service.uuid)
            if conn is None or conn.status == "revoked":
                state = "not_connected"
            elif conn.status == "expired":
                state = "expired"
            elif registry.get_active_bundle(service.uuid) is None:
                state = "not_published"
            elif not conn.enabled:
                state = "off"
            else:
                state = "ok"
            cache[service.uuid] = engine.Access(state)
        return cache[service.uuid]

    return access


@router.post("/assistant/ask")
async def ask(body: AskBody, user_id: str = Depends(get_current_user)) -> dict:
    from backend.app.gateway.router import invoke

    loop = asyncio.get_running_loop()

    def call(service: engine.ServiceInfo, tool: engine.ToolInfo, args: dict) -> dict:
        # The engine runs in a worker thread; tool calls go back to the event loop.
        t0 = time.monotonic()
        res = asyncio.run_coroutine_threadsafe(invoke(user_id, service.uuid, tool.name, args), loop).result(45)
        return {**res, "ms": int((time.monotonic() - t0) * 1000)}

    def turn() -> dict:
        services = engine.load_services()
        return engine.answer(text=body.text, pending=body.pending, memory=body.memory,
                             services=services, access=_access_for(user_id), call=call)

    out = await asyncio.to_thread(turn)
    return {**out, "user_id": user_id}
