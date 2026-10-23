"""Gateway guard rails: a per-user rate limit on tool calls, and an upstream allow-list (SSRF).

Allow-list: a tool may only call its own service's base URL (the gateway passes it in; tools
never choose a host). That URL is refused when it points inside our network, unless it is:
  - a configured UPSTREAM_REWRITES target (e.g. http://demo-api:9000 in Docker), or
  - a local host while MODE=local (the laptop demo's mock APIs on localhost), or
  - listed in ALLOWED_UPSTREAM_HOSTS (comma-separated host names).
So a submitted manifest pointing at http://169.254.169.254/ or an internal service is refused.
"""
import ipaddress
import os
import socket
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from backend.app.auth.settings import get_settings

DEFAULT_CALLS_PER_MINUTE = 60
_LOCAL_NAMES = {"localhost", "host.docker.internal"}


class RateLimiter:
    """Sliding one-minute window per key. In memory: one gateway process (fine for the demo;
    several instances behind a load balancer would share it through Redis)."""

    def __init__(self, per_minute: int | None = None):
        self._per_minute = per_minute
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    @property
    def per_minute(self) -> int:
        if self._per_minute is not None:
            return self._per_minute
        return int(os.getenv("RATE_LIMIT_PER_MINUTE", str(DEFAULT_CALLS_PER_MINUTE)))

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


tool_calls = RateLimiter()


def _private(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast


def upstream_problem(base_url: str | None) -> str | None:
    """None if the (already rewritten) base URL may be called, else why not. Blocking (DNS)."""
    if not base_url:
        return "this service has no API address"
    s = get_settings()
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return "the service's API address isn't an http(s) URL"
    if any(base_url.startswith(target) for target in s.upstream_rewrites.values()):
        return None
    extra = {h.strip().lower() for h in os.getenv("ALLOWED_UPSTREAM_HOSTS", "").split(",") if h.strip()}
    if host in extra:
        return None
    try:
        ips = [host] if _is_ip(host) else sorted({i[4][0] for i in socket.getaddrinfo(host, None)})
    except OSError:
        return f"{host} can't be resolved"
    local = host in _LOCAL_NAMES or any(_private(ip) for ip in ips)
    if local and s.mode == "local" and (host in _LOCAL_NAMES or all(ipaddress.ip_address(ip).is_loopback for ip in ips)):
        return None  # the laptop demo: mock APIs on localhost
    if local:
        return f"{host} is an internal address; the gateway only calls public APIs"
    return None


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
