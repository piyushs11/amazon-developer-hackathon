"""Gateway guard rails: per-user rate limit and the upstream allow-list (SSRF)."""
import pytest

from backend.app.gateway.safety import RateLimiter, upstream_problem


def test_rate_limit_is_per_user_and_per_minute():
    limiter = RateLimiter(per_minute=3)
    assert all(limiter.allow("alice", now=t) for t in (0, 1, 2))
    assert not limiter.allow("alice", now=3)
    assert limiter.allow("bob", now=3)  # other users are not affected
    assert limiter.allow("alice", now=61)  # the window moved on


@pytest.fixture
def env(monkeypatch):
    def set_env(mode="local", rewrites="", extra=""):
        monkeypatch.setenv("MODE", mode)
        for name in ("PLATFORM_JWT_SECRET", "OAUTH_STATE_SECRET", "TOKEN_ENC_KEY"):
            monkeypatch.setenv(name, "x" * 40)
        monkeypatch.setenv("UPSTREAM_REWRITES", rewrites)
        monkeypatch.setenv("ALLOWED_UPSTREAM_HOSTS", extra)
    return set_env


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data",  # cloud metadata
    "http://10.0.0.5/admin",
    "http://192.168.1.1/",
    "file:///etc/passwd",
])
def test_internal_addresses_are_refused(env, url):
    env(mode="aws")
    assert upstream_problem(url)


def test_localhost_only_in_local_mode(env):
    env(mode="local")
    assert upstream_problem("http://localhost:9000") is None
    env(mode="aws")
    assert "internal" in upstream_problem("http://localhost:9000")


def test_configured_rewrite_targets_and_extra_hosts_are_allowed(env):
    env(mode="aws", rewrites="http://localhost:9000=http://10.1.2.3:9000", extra="10.9.9.9")
    assert upstream_problem("http://10.1.2.3:9000/menu") is None
    assert upstream_problem("http://10.9.9.9/x") is None
    assert upstream_problem("http://10.1.2.4/x")
