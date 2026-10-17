from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import gateway
from backend.app.auth import factory as auth_factory
from backend.app.auth.router import router as auth_router
from backend.app.auth.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    auth_factory.configure()  # Dev 3: token provider used by runtime/client.py
    yield


app = FastAPI(title="MCP Bridge", lifespan=lifespan)

# The browser simulator calls /mcp/* directly with an Authorization header.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_url],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "MCP-Protocol-Version"],
)

app.include_router(auth_router)  # Dev 3: POST /auth/demo-login
app.include_router(gateway.router)  # Dev 3: POST /mcp/{service_uuid}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
