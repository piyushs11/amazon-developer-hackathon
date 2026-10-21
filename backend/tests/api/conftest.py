import httpx
import pytest
from fastapi import FastAPI

from backend.app.api import jobs
from backend.tests.dev3_support import dev3_env, route_upstream  # noqa: F401


@pytest.fixture
def api_app(dev3_env):  # noqa: F811
    from backend.app.api.router import router as api_router
    from backend.app.auth.router import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(api_router)
    return app


@pytest.fixture
async def api(api_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app),
                                 base_url="http://api.test") as client:
        yield client


@pytest.fixture(autouse=True)
def fresh_jobs():
    jobs.set_jobs(None)
    yield
    jobs.set_jobs(None)
