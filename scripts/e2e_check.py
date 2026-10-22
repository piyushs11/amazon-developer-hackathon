"""End-to-end check of a running MCP Bridge stack (laptop Docker or EC2), over HTTP only.

    python scripts/e2e_check.py                      # http://localhost:8000
    python scripts/e2e_check.py https://<domain>     # EC2

Walks the whole demo path for two users and checks the security rules on the way:
    login -> resolve-service -> oauth (fake provider) -> publish (poll) -> me/services
    -> MCP initialize / tools/list / tools/call -> second user (skips generation, own data)
    -> no token = bare 401 -> logged-in but not connected = "please connect"
Exit code 0 only if every check passed.
"""
import sys
import time

import httpx

API = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
DEMO = "11111111-1111-1111-1111-111111111111"
PUBLISH_TIMEOUT = 300  # first publish with VERIFY=llm calls Bedrock for every tool
failures = 0


def check(ok: bool, what: str, detail: object = "") -> bool:
    global failures
    print(("  PASS " if ok else "  FAIL ") + what + (f"  ->  {detail}" if detail != "" and not ok else ""))
    failures += not ok
    return ok


def login(client: httpx.Client, name: str) -> dict:
    resp = client.post(f"{API}/auth/demo-login", json={"username": name})
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['user_token']}"}


def connect(client: httpx.Client, headers: dict) -> None:
    start = client.get(f"{API}/oauth/start", params={"service_uuid": DEMO}, headers=headers)
    check(start.status_code == 200, "GET /oauth/start returns an auth_url", start.text)
    # The fake provider auto-approves: authorize -> 302 to our /oauth/callback -> 302 to the UI.
    authorize = client.get(start.json()["auth_url"])
    check(authorize.status_code in (302, 307), "fake authorize page redirects back", authorize.status_code)
    callback = client.get(authorize.headers["location"])
    location = callback.headers.get("location", "")
    check(callback.status_code == 302 and location.endswith("/connect/done?status=ok"),
          "GET /oauth/callback stores the token and redirects to /connect/done?status=ok", location)


def publish(client: httpx.Client, headers: dict) -> dict:
    job = client.post(f"{API}/publish", json={"service_uuid": DEMO}, headers=headers).json()["job_id"]
    stages, deadline = [], time.monotonic() + PUBLISH_TIMEOUT
    while time.monotonic() < deadline:
        status = client.get(f"{API}/publish/{job}", headers=headers).json()
        if not stages or stages[-1] != status["stage"]:
            stages.append(status["stage"])
        if status["status"] != "running":
            print(f"       stages: {' -> '.join(stages)}")
            return status
        time.sleep(1)
    return {"status": "timeout", "stage": stages[-1] if stages else None}


def mcp(client: httpx.Client, headers: dict, method: str, params: dict | None = None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post(f"{API}/mcp/{DEMO}", json=body,
                       headers={**headers, "Accept": "application/json, text/event-stream"})


def call(client: httpx.Client, headers: dict, tool: str, args: dict) -> dict:
    resp = mcp(client, headers, "tools/call", {"name": tool, "arguments": args})
    return resp.json().get("result", resp.json())


def main() -> int:
    print(f"MCP Bridge end-to-end check against {API}\n")
    with httpx.Client(timeout=30) as client:
        print("1. health")
        check(client.get(f"{API}/health").json() == {"status": "ok"}, "GET /health")

        print("2. alice: login, find, connect, publish")
        alice = login(client, "alice")
        found = client.post(f"{API}/resolve-service", json={"query": "https://www.demobistro.test/menu"},
                            headers=alice).json()
        check(found.get("status") == "resolved" and found["service"]["service_uuid"] == DEMO,
              "POST /resolve-service finds Demo Bistro by URL", found)
        connect(client, alice)
        result = publish(client, alice)
        check(result["status"] == "done" and result.get("mcp_url", "").endswith(f"/mcp/{DEMO}"),
              f"publish done (skipped={result.get('skipped')}, version={result.get('version')})", result)
        services = client.get(f"{API}/me/services", headers=alice).json()
        check(any(s["service_uuid"] == DEMO and s["status"] == "active" for s in services),
              "GET /me/services shows Demo Bistro active", services)

        print("3. alice: MCP calls through the gateway")
        init = mcp(client, alice, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                  "clientInfo": {"name": "e2e", "version": "1"}})
        check(init.status_code == 200 and "protocolVersion" in init.json().get("result", {}), "initialize")
        tools = mcp(client, alice, "tools/list").json().get("result", {}).get("tools", [])
        names = sorted(t["name"] for t in tools)
        check(names == ["get_order_status", "place_order", "search_menu"], "tools/list has 3 tools", names)
        menu = call(client, alice, "search_menu", {"query": "pasta"})
        check(not menu.get("isError") and len(menu.get("structuredContent", {}).get("results", [])) == 2,
              "search_menu(pasta) returns 2 dishes", menu)
        order = call(client, alice, "get_order_status", {"order_id": "A1042"})
        alice_status = order.get("structuredContent", {}).get("status")
        check(alice_status == "out for delivery", "get_order_status(A1042) uses alice's account", order)
        placed = call(client, alice, "place_order", {"item": "Tiramisu", "quantity": 2})
        check(not placed.get("isError") and placed.get("structuredContent", {}).get("quantity") == 2,
              "place_order(Tiramisu x2) succeeds", placed)
        missing = call(client, alice, "get_order_status", {"order_id": "Z9999"})
        check(missing.get("isError") is True, "unknown order -> isError", missing)
        bad = call(client, alice, "search_menu", {})
        check(bad.get("isError") is True, "missing required argument -> isError", bad)

        print("4. bob: same MCP URL, generation skipped, his own data")
        bob = login(client, "bob")
        connect(client, bob)
        result = publish(client, bob)
        check(result["status"] == "done" and result.get("skipped") is True,
              "second user's publish is skipped (bundle already live)", result)
        order = call(client, bob, "get_order_status", {"order_id": "A1042"})
        bob_status = order.get("structuredContent", {}).get("status")
        check(bob_status == "being prepared" and bob_status != alice_status,
              "bob gets HIS order A1042, not alice's", order)

        print("5. access rules")
        resp = mcp(client, {}, "tools/list")
        check(resp.status_code == 401 and "www-authenticate" not in resp.headers,
              "no token -> bare 401 (no WWW-Authenticate)", resp.headers)
        resp = mcp(client, {"Authorization": "Bearer nonsense"}, "tools/list")
        check(resp.status_code == 401, "bad token -> 401", resp.status_code)
        carol = login(client, "carol")
        result = call(client, carol, "get_order_status", {"order_id": "A1042"})
        text = (result.get("content") or [{}])[0].get("text", "")
        check(result.get("isError") is True and "connect" in text.lower(),
              "logged in but not connected -> 'please connect'", result)

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
