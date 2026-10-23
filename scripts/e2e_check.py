"""End-to-end check of a running MCP Bridge stack (laptop Docker or EC2), over HTTP only.

    python scripts/e2e_check.py                      # http://localhost:8000
    python scripts/e2e_check.py https://<domain>     # EC2

Walks the whole demo path for two users and checks the security rules on the way:
    login -> resolve-service -> oauth (fake provider) -> publish (poll) -> me/services
    -> MCP initialize / tools/list / tools/call -> second user (skips generation, own data)
    -> no token = bare 401 -> logged-in but not connected = "please connect"
then the data-driven parts (everything comes from the seeded Postgres):
    catalog + demo users -> search by name / name + city -> Lakeside Dental (generated on
    first publish) -> Ask mode (/assistant/ask) incl. a write with a yes -> on/off switch
    -> an expired connection and reconnect -> owner/reviewer roles -> review "Try it" and
    approval of the pending Pine & Petal -> it can be found -> per-user rate limit
Re-runnable: steps that already happened on this database are reported as skipped.
Exit code 0 only if every check passed.
"""
import sys
import time

import httpx

API = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
DEMO = "11111111-1111-1111-1111-111111111111"
DENTAL = "22222222-2222-2222-2222-222222222222"
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


def connect(client: httpx.Client, headers: dict, uuid: str = DEMO) -> None:
    start = client.get(f"{API}/oauth/start", params={"service_uuid": uuid}, headers=headers)
    check(start.status_code == 200, "GET /oauth/start returns an auth_url", start.text)
    # The fake provider auto-approves: authorize -> 302 to our /oauth/callback -> 302 to the UI.
    authorize = client.get(start.json()["auth_url"])
    check(authorize.status_code in (302, 307), "fake authorize page redirects back", authorize.status_code)
    callback = client.get(authorize.headers["location"])
    location = callback.headers.get("location", "")
    check(callback.status_code == 302 and location.endswith("/connect/done?status=ok"),
          "GET /oauth/callback stores the token and redirects to /connect/done?status=ok", location)


def publish(client: httpx.Client, headers: dict, uuid: str = DEMO) -> dict:
    job = client.post(f"{API}/publish", json={"service_uuid": uuid}, headers=headers).json()["job_id"]
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


def mcp(client: httpx.Client, headers: dict, method: str, params: dict | None = None,
        uuid: str = DEMO):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post(f"{API}/mcp/{uuid}", json=body,
                       headers={**headers, "Accept": "application/json, text/event-stream"})


def call(client: httpx.Client, headers: dict, tool: str, args: dict, uuid: str = DEMO) -> dict:
    resp = mcp(client, headers, "tools/call", {"name": tool, "arguments": args}, uuid)
    return resp.json().get("result", resp.json())


def ask(client: httpx.Client, headers: dict, text: str, pending=None, memory=None) -> dict:
    body = {"text": text, "pending": pending, "memory": memory or {}}
    return client.post(f"{API}/assistant/ask", json=body, headers=headers).json()


def mine(client: httpx.Client, headers: dict) -> dict:
    return {s["service_uuid"]: s for s in client.get(f"{API}/me/services", headers=headers).json()}


def skip(what: str) -> None:
    print("  SKIP " + what)


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

        data_driven(client, alice, bob)

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


def data_driven(client: httpx.Client, alice: dict, bob: dict) -> None:
    print("6. catalog, demo users and search (from Postgres)")
    users = [u["user_id"] for u in client.get(f"{API}/auth/demo-users").json()]
    check({"alice", "bob"} <= set(users), "GET /auth/demo-users lists the seeded users", users)
    catalog = {s["service_name"]: s for s in client.get(f"{API}/services", headers=alice).json()}
    check({"Demo Bistro", "Lakeside Dental", "Lakeside Grill"} <= set(catalog)
          and all(s["profile"].get("city") for s in catalog.values()),
          "GET /services lists the seeded catalog with profiles", list(catalog))
    found = client.post(f"{API}/resolve-service", json={"query": "Lakeside"}, headers=alice).json()
    check(found["status"] == "ambiguous" and len(found["candidates"]) == 2,
          "'Lakeside' is ambiguous", found)
    found = client.post(f"{API}/resolve-service", json={"query": "Lakeside in Chicago"},
                        headers=alice).json()
    check(found["status"] == "resolved" and found["service"]["service_name"] == "Lakeside Grill",
          "'Lakeside in Chicago' picks Lakeside Grill", found)

    print("7. alice: Lakeside Dental (generated on its first publish)")
    if mine(client, alice).get(DENTAL, {}).get("status") != "active":
        connect(client, alice, DENTAL)
        result = publish(client, alice, DENTAL)
        check(result["status"] == "done", f"publish Lakeside Dental (skipped={result.get('skipped')})",
              result)
    else:
        skip("Lakeside Dental already live for alice")
    tools = mcp(client, alice, "tools/list", uuid=DENTAL).json().get("result", {}).get("tools", [])
    check(len(tools) == 4, "Lakeside Dental tools/list has 4 tools", [t["name"] for t in tools])
    slots = call(client, alice, "next_available", {"visit_type": "cleaning"}, DENTAL)
    check(not slots.get("isError") and "slots" in slots.get("structuredContent", {}),
          "next_available returns slots from the mock API", slots)

    print("8. Ask mode (/assistant/ask): phrases and templates from the database")
    out = ask(client, alice, "what is the status of order A1042")
    check(out.get("call", {}).get("tool") == "get_order_status" and "out for delivery" in out["reply"],
          "status question -> get_order_status, answer from the template", out.get("reply"))
    out = ask(client, alice, "order 2 tiramisu from Demo Bistro")
    check(out["kind"] == "confirm" and out["pending"]["arguments"] == {"item": "Tiramisu", "quantity": 2},
          "a write asks first, with the arguments filled in", out)
    done = ask(client, alice, "yes", out["pending"], out["memory"])
    check(done.get("call", {}).get("tool") == "place_order" and "Done." in done["reply"],
          "yes -> place_order runs", done.get("reply"))
    out = ask(client, alice, "when is the next cleaning at Lakeside Dental", None, done["memory"])
    check(out.get("call", {}).get("tool") == "next_available", "Lakeside Dental works in Ask mode",
          out.get("reply"))

    print("8b. Ask mode: one conversation across services (Bistro -> Dental -> Bistro)")
    out = ask(client, alice, "what pasta does Demo Bistro have")
    check(out.get("via", {}).get("service") == "Demo Bistro" and out.get("call", {}).get("tool") == "search_menu",
          "turn 1 -> Demo Bistro search_menu", out.get("via"))
    out = ask(client, alice, "when is the next cleaning at Lakeside Dental", None, out["memory"])
    check(out.get("via") == {"service": "Lakeside Dental", "tool": "next_available", "switched": True}
          and out["reply"].startswith("Lakeside Dental:"),
          "turn 2 -> switches to Lakeside Dental, and says so", out.get("via"))
    memory = out["memory"]
    out = ask(client, alice, "what dessert does Demo Bistro have", None, memory)
    check(out.get("via", {}).get("service") == "Demo Bistro" and out["via"]["switched"] is True,
          "turn 3 -> back to Demo Bistro", out.get("via"))
    order = ask(client, alice, "order a margherita pizza from Demo Bistro", None, out["memory"])
    check(order["kind"] == "confirm", "a write is pending at the Bistro", order.get("reply"))
    out = ask(client, alice, "okay book a dentist appointment", order["pending"], order["memory"])
    check(out.get("via", {}).get("service") == "Lakeside Dental" and out["pending"] is None
          and out.get("call", {}).get("tool") != "place_order",
          "changing topic drops the pending order (no accidental place_order)", out.get("reply"))
    out = ask(client, alice, "where is my Demo Bistro order", None, {"ids": {DENTAL: {"order_id": "ZZZ"}}})
    check(out["kind"] == "clarify" and not out.get("call"),
          "an id remembered for Lakeside Dental is not used for a Demo Bistro tool", out.get("reply"))
    out = ask(client, bob, "what are the specials at Lakeside Grill")
    check(out["kind"] == "blocked" and "connect" in out["reply"].lower(),
          "a service bob never connected -> 'please connect'", out.get("reply"))

    print("9. on/off switch")
    client.patch(f"{API}/me/services/{DEMO}", json={"enabled": False}, headers=alice)
    off = call(client, alice, "search_menu", {"query": "pasta"})
    check(off.get("isError") is True and "switched off" in off["content"][0]["text"],
          "switched off -> the gateway refuses", off)
    client.patch(f"{API}/me/services/{DEMO}", json={"enabled": True}, headers=alice)
    check(not call(client, alice, "search_menu", {"query": "pasta"}).get("isError"),
          "switched on again -> works")

    print("10. bob: expired Lakeside Dental -> reconnect")
    state = mine(client, bob).get(DENTAL, {}).get("status")
    if state == "expired":
        res = call(client, bob, "my_appointments", {}, DENTAL)
        check(res.get("isError") and "reconnect" in res["content"][0]["text"].lower(),
              "expired -> 'reconnect'", res)
        connect(client, bob, DENTAL)
        check(mine(client, bob)[DENTAL]["status"] in ("active", "connected"),
              "reconnect makes it active again")
    else:
        skip(f"bob's Lakeside Dental is {state} (already reconnected on this database)")

    print("11. owner and reviewer roles; review and approve the pending submission")
    check(client.get(f"{API}/api/review/submissions", headers=alice).status_code == 403,
          "user -> /api/review is 403")
    owner = login(client, "pinepetal-owner")
    check(client.get(f"{API}/api/review/submissions", headers=owner).status_code == 403,
          "owner -> /api/review is 403")
    reviewer = login(client, "reviewer")
    queue = client.get(f"{API}/api/review/submissions", headers=reviewer).json()
    pending = next((s for s in queue if s["domain"] == "pinepetal.test"
                    and s["status"] in ("pending", "in_review")), None)
    if pending:
        tried = client.post(f"{API}/api/review/submissions/{pending['id']}/try", headers=reviewer,
                            json={"tool": "search_bouquets", "arguments": {"occasion": "roses"}}).json()
        check(tried.get("status") == 200 and tried["data"]["bouquets"],
              "Try it calls the real API with the test account", tried)
        approved = client.post(f"{API}/api/review/submissions/{pending['id']}/approve",
                               headers=reviewer, json={"note": "e2e"}).json()
        check(approved.get("status") == "approved", "approve", approved)
    else:
        skip("Pine & Petal has no open submission (already reviewed on this database)")
    found = client.post(f"{API}/resolve-service", json={"query": "pinepetal.test"}, headers=alice).json()
    check(found["status"] == "resolved", "the approved service can be found by its website", found)

    print("12. per-user rate limit on tool calls")
    flood = login(client, "ratelimit-check")
    codes = [mcp(client, flood, "tools/call", {"name": "search_menu", "arguments": {"query": "x"}}).status_code
             for _ in range(70)]
    check(429 in codes and codes.index(429) >= 50, "too many calls in a minute -> 429", codes[-5:])


if __name__ == "__main__":
    sys.exit(main())
