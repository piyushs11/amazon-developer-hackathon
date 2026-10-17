import uuid

import pytest
import redis

from backend.app.storage.tool_cache import ToolCache

TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest.fixture
def cache():
    """A ToolCache on a real local Redis (db 15) with a unique key prefix, cleaned afterwards."""
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError:
        pytest.skip("Redis is not running on localhost:6379 (brew services start redis)")
    tool_cache = ToolCache(client, prefix=f"test-{uuid.uuid4().hex[:8]}")
    yield tool_cache
    tool_cache.delete_all()
