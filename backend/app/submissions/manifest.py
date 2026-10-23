"""Connector manifest (what a business uploads in the Owner Portal) <-> our C1 spec.

A manifest has four blocks:
    publisher       name, domain, description, category, city, brandColor, privacy/terms URLs
    accountLinking  OAuth 2 authorization-code settings (authorizationUrl, tokenUrl, scopes)
    private         clientSecret, testAccount {username, password}, reviewNotes (never public)
    openapi         OpenAPI 3.x: servers, paths with operationId, components; each operation
                    may carry `x-alexa` (examplePhrases, sideEffect, requiresConfirmation,
                    confirmationPrompt, speakableResponse, emptyResponse, errorResponses, exampleArgs)

manifest_to_spec() turns it into C1 (+ profile), so approval runs the same parse_spec ->
map_service path as the catalog seed. run_checks() is the 8-check report shown to owners and
reviewers. spec_to_manifest() goes the other way for the seeded catalog services.
"""
import re
import uuid
from urllib.parse import urlsplit

from backend.app.mapper import MapError, map_service
from backend.app.mapper.mapper import _sanitise
from backend.app.spec import SpecError, parse_spec

METHODS = ("get", "post", "put", "patch", "delete")
JSON_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
MAX_ENDPOINTS = 20
# Hosts that can't be on the public internet: allowed (with a warning) for the local demo.
LOCAL_SUFFIXES = (".test", ".example", ".local", ".localhost", ".invalid")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}

GLYPHS = {"food": "utensils", "health": "calendar", "shopping": "bag", "home": "home"}
PALETTE = ["#b23a1e", "#1f6f8b", "#2f6b3a", "#6b4ee6", "#a3456b", "#8a5a00", "#2b5797"]


def is_local_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return host in LOCAL_HOSTS or host.endswith(LOCAL_SUFFIXES) or host in {s.lstrip(".") for s in LOCAL_SUFFIXES}


def _host(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def service_uuid_for(domain: str) -> str:
    """The registered service for this domain keeps its uuid; a new domain gets a stable one."""
    from backend.app.db import registry

    row = registry.find_by_domain(domain)
    return row.service_uuid if row else str(uuid.uuid5(uuid.NAMESPACE_DNS, domain))


# ---- reading the manifest ----

def _resolve_ref(api: dict, schema: dict | None) -> dict:
    if not isinstance(schema, dict):
        return {}
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/components/schemas/"):
        raise ValueError(f"unsupported $ref {ref}")
    name = ref.rsplit("/", 1)[-1]
    target = (api.get("components") or {}).get("schemas", {}).get(name)
    if target is None:
        raise ValueError(f"$ref {ref} does not resolve")
    return target


def _json_type(schema: dict) -> str:
    if schema.get("enum"):
        return "string"
    t = schema.get("type", "string")
    return t if t in JSON_TYPES else "string"


def operations(manifest: dict) -> list[tuple[str, str, dict]]:
    """(path, METHOD, operation) for every operation, in document order."""
    out = []
    for path, item in ((manifest.get("openapi") or {}).get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() in METHODS and isinstance(op, dict):
                out.append((path, method.upper(), op))
    return out


def tools_from_manifest(manifest: dict) -> list[dict]:
    """The MCP tools a manifest turns into, for the Owner wizard and the review screen."""
    api = manifest.get("openapi") or {}
    tools = []
    for path, method, op in operations(manifest):
        ax = op.get("x-alexa") or {}
        params = []
        for p in op.get("parameters") or []:
            schema = _resolve_ref(api, p.get("schema"))
            params.append({"name": p.get("name"), "in": p.get("in"), "required": bool(p.get("required")),
                           "type": _json_type(schema), "description": p.get("description") or "",
                           "enum": schema.get("enum")})
        body = ((op.get("requestBody") or {}).get("content") or {}).get("application/json", {}).get("schema")
        if body:
            body = _resolve_ref(api, body)
            for name, prop in (body.get("properties") or {}).items():
                prop = _resolve_ref(api, prop)
                params.append({"name": name, "in": "body", "required": name in (body.get("required") or []),
                               "type": _json_type(prop), "description": prop.get("description") or "",
                               "enum": prop.get("enum")})
        params.sort(key=lambda p: not p["required"])  # required first (C2)
        side_effect = ax.get("sideEffect") or ("none" if method == "GET" else "write")
        tools.append({
            "name": op.get("operationId"), "title": op.get("summary") or op.get("operationId"),
            "description": op.get("description") or op.get("summary") or "",
            "method": method, "path": path, "read_only": method == "GET", "side_effect": side_effect,
            "params": params,
            "requires_confirmation": bool(ax.get("requiresConfirmation")),
            "confirmation_prompt": ax.get("confirmationPrompt"),
            "speakable_response": ax.get("speakableResponse"),
            "empty_response": ax.get("emptyResponse"),
            "error_responses": {str(k): v for k, v in (ax.get("errorResponses") or {}).items()},
            "example_phrases": list(ax.get("examplePhrases") or []),
            "example_args": dict(ax.get("exampleArgs") or {}),
        })
    return tools


def _scope_labels(manifest: dict) -> dict:
    linking = manifest.get("accountLinking") or {}
    labels = dict(linking.get("scopeLabels") or {})
    schemes = ((manifest.get("openapi") or {}).get("components") or {}).get("securitySchemes") or {}
    for scheme in schemes.values():
        for flow in ((scheme or {}).get("flows") or {}).values():
            labels.update({k: v for k, v in (flow.get("scopes") or {}).items() if k not in labels})
    return {s: labels.get(s, s) for s in linking.get("scopes") or []}


def profile_from_manifest(manifest: dict) -> dict:
    pub = manifest.get("publisher") or {}
    name = pub.get("name") or ""
    tools = tools_from_manifest(manifest)
    category = pub.get("category") or "Service"
    glyph = next((g for k, g in GLYPHS.items() if k in category.lower()), "globe")
    phrases = [p for t in tools for p in t["example_phrases"][:1]][:3]
    return {
        "description": pub.get("description") or "",
        "tagline": pub.get("tagline") or ((manifest.get("openapi") or {}).get("info") or {}).get("description", ""),
        "category": category, "city": pub.get("city") or "",
        "color": pub.get("brandColor") or PALETTE[sum(map(ord, name)) % len(PALETTE)],
        "initials": "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name)[:2]).upper() or "?",
        "glyph": glyph,
        "auth_host": _host((manifest.get("accountLinking") or {}).get("authorizationUrl")),
        "privacy_url": pub.get("privacyPolicyUrl") or "", "terms_url": pub.get("termsUrl") or "",
        "scope_labels": _scope_labels(manifest),
        "phrases": phrases,
        "tools": {
            t["name"]: {k: v for k, v in {
                "title": t["title"], "side_effect": t["side_effect"],
                "example_phrases": t["example_phrases"],
                # Keyed like the tool's inputs: the mapper renames "filter.term" -> "filter_term".
                "example_args": {_sanitise(k): v for k, v in t["example_args"].items()} or None,
                "requires_confirmation": t["requires_confirmation"] or None,
                "confirmation_prompt": t["confirmation_prompt"], "speakable_response": t["speakable_response"],
                "empty_response": t["empty_response"], "error_responses": t["error_responses"] or None,
            }.items() if v not in (None, "", [])}
            for t in tools if t["name"]
        },
    }


def manifest_to_spec(manifest: dict, service_uuid: str) -> dict:
    """The C1 spec (raw dict, before parse_spec) for this manifest."""
    pub = manifest.get("publisher") or {}
    linking = manifest.get("accountLinking") or {}
    api = manifest.get("openapi") or {}
    endpoints = []
    for t in tools_from_manifest(manifest):
        endpoints.append({
            "id": t["name"], "path": t["path"], "method": t["method"], "description": t["description"],
            "params": [{"name": p["name"], "type": p["type"], "required": p["required"],
                        "location": p["in"], "description": p["description"] or None} for p in t["params"]],
        })
    return {
        "service_uuid": service_uuid,
        "service_name": pub.get("name"),
        "domain": (pub.get("domain") or "").lower(),
        "base_url": ((api.get("servers") or [{}])[0].get("url") or "").rstrip("/"),
        "auth_type": "oauth2",
        "oauth": {"auth_url": linking.get("authorizationUrl"), "token_url": linking.get("tokenUrl"),
                  "scopes": list(linking.get("scopes") or [])},
        "endpoints": endpoints,
        "profile": profile_from_manifest(manifest),
    }


# ---- the other way: a catalog spec as a manifest (seeded services) ----

def spec_to_manifest(spec: dict, version: str, *, owner_email: str, test_account: dict) -> dict:
    profile = spec.get("profile") or {}
    tool_profiles = profile.get("tools") or {}
    paths: dict = {}
    for e in spec["endpoints"]:
        tp = tool_profiles.get(e["id"], {})
        op: dict = {"operationId": e["id"], "summary": tp.get("title", e["id"]), "description": e["description"]}
        plain = [p for p in e["params"] if p["location"] != "body"]
        body = [p for p in e["params"] if p["location"] == "body"]
        if plain:
            op["parameters"] = [{"name": p["name"], "in": p["location"], "required": p["required"],
                                 "description": p.get("description") or "", "schema": {"type": p["type"]}}
                                for p in plain]
        if body:
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {p["name"]: {"type": p["type"], "description": p.get("description") or ""} for p in body},
                "required": [p["name"] for p in body if p["required"]]}}}}
        ax = {"examplePhrases": tp.get("example_phrases", []), "sideEffect": tp.get("side_effect", "none"),
              "requiresConfirmation": bool(tp.get("requires_confirmation")),
              "confirmationPrompt": tp.get("confirmation_prompt"), "speakableResponse": tp.get("speakable_response"),
              "emptyResponse": tp.get("empty_response"), "errorResponses": tp.get("error_responses"),
              "exampleArgs": tp.get("example_args")}
        op["x-alexa"] = {k: v for k, v in ax.items() if v not in (None, {}, [])}
        paths.setdefault(e["path"], {})[e["method"].lower()] = op
    oauth = spec.get("oauth") or {}
    return {
        "manifestVersion": "1.0",
        "publisher": {
            "name": spec["service_name"], "domain": spec["domain"], "description": profile.get("description", ""),
            "tagline": profile.get("tagline", ""), "category": profile.get("category", ""),
            "city": profile.get("city", ""), "brandColor": profile.get("color"),
            "privacyPolicyUrl": profile.get("privacy_url", ""), "termsUrl": profile.get("terms_url", ""),
            "contactEmail": owner_email,
        },
        "accountLinking": {
            "type": "oauth2_authorization_code", "authorizationUrl": oauth.get("auth_url"),
            "tokenUrl": oauth.get("token_url"), "clientId": "mcp-bridge", "tokenAuthMethod": "client_secret_post",
            "scopes": oauth.get("scopes", []), "scopeLabels": profile.get("scope_labels", {}), "pkce": False,
        },
        "private": {"clientSecret": "stored-in-secrets-store", "testAccount": test_account,
                    "reviewNotes": "Test account has sample data for every tool."},
        "openapi": {
            "openapi": "3.1.0",
            "info": {"title": spec["service_name"] + " API", "version": version,
                     "description": profile.get("tagline", "")},
            "servers": [{"url": spec["base_url"]}],
            "paths": paths,
        },
    }


# ---- checks ----

CHECKS = [
    ("schema", "Manifest schema is valid"),
    ("openapi", "OpenAPI spec is valid and maps to MCP tools"),
    ("https", "HTTPS everywhere"),
    ("hosted", "Hosted copy matches the upload"),
    ("domain", "API host is on the owner's domain"),
    ("voice", "Every endpoint is ready for voice"),
    ("confirm", "Write and payment endpoints require confirmation"),
    ("limit", f"{MAX_ENDPOINTS} endpoints or fewer"),
]


def _missing(d: dict, keys: list[str]) -> list[str]:
    return [k for k in keys if not (d or {}).get(k)]


def _check_schema(m: dict) -> tuple[str, str]:
    problems = []
    if m.get("manifestVersion") != "1.0":
        problems.append("manifestVersion must be \"1.0\"")
    for block in ("publisher", "accountLinking", "private", "openapi"):
        if not isinstance(m.get(block), dict):
            problems.append(f"{block} block is missing")
    problems += [f"publisher.{k} is missing" for k in _missing(m.get("publisher"), ["name", "domain", "description"])]
    problems += [f"accountLinking.{k} is missing"
                 for k in _missing(m.get("accountLinking"), ["authorizationUrl", "tokenUrl", "scopes"])]
    if not ((m.get("private") or {}).get("testAccount") or {}).get("username"):
        problems.append("private.testAccount.username is missing (reviewers need it)")
    if problems:
        return "err", "; ".join(problems) + "."
    return "ok", "manifestVersion 1.0 with publisher, accountLinking, private and openapi blocks present."


def _check_openapi(m: dict) -> tuple[str, str]:
    api = m.get("openapi") or {}
    problems = []
    if not str(api.get("openapi", "")).startswith("3."):
        problems.append("openapi must be 3.x")
    if not ((api.get("servers") or [{}])[0] or {}).get("url"):
        problems.append("servers[0].url is missing")
    ops = operations(m)
    if not ops:
        problems.append("no operations under paths")
    ids = [op.get("operationId") for _, _, op in ops]
    if any(not i for i in ids):
        problems.append("every operation needs an operationId")
    dupes = sorted({i for i in ids if i and ids.count(i) > 1})
    if dupes:
        problems.append(f"duplicate operationId {', '.join(dupes)}")
    if not problems:
        try:
            spec = parse_spec(manifest_to_spec(m, "00000000-0000-0000-0000-000000000000"))
            map_service(spec)
        except (SpecError, MapError, ValueError) as exc:
            problems.append(f"can't be turned into tools: {exc}")
    if problems:
        return "err", "; ".join(problems) + "."
    info = api.get("info") or {}
    return "ok", (f"OpenAPI {api.get('openapi')} · {info.get('title', '')} {info.get('version', '')} · "
                  f"{len(ops)} operations, all mapped to MCP tools.")


def _check_https(m: dict) -> tuple[str, str]:
    pub, linking, api = m.get("publisher") or {}, m.get("accountLinking") or {}, m.get("openapi") or {}
    urls = {"API server": ((api.get("servers") or [{}])[0] or {}).get("url"),
            "authorization": linking.get("authorizationUrl"), "token": linking.get("tokenUrl"),
            "revocation": linking.get("revocationUrl"), "privacy": pub.get("privacyPolicyUrl"),
            "terms": pub.get("termsUrl"), "logo": pub.get("logoUrl")}
    plain = {k: u for k, u in urls.items() if u and not u.startswith("https://")}
    bad = {k: u for k, u in plain.items() if not is_local_host(_host(u))}
    if bad:
        return "err", "Not https: " + ", ".join(f"{k} ({u})" for k, u in bad.items()) + "."
    if plain:
        return "warn", ("Allowed for local mock services only: " + ", ".join(plain) +
                        " use http on a local host. Public services must use https.")
    return "ok", "API server, authorization, token, privacy, terms and logo URLs all use https."


def _check_hosted(m: dict) -> tuple[str, str]:
    import httpx

    domain = ((m.get("publisher") or {}).get("domain") or "").lower()
    if not domain:
        return "err", "publisher.domain is missing."
    if is_local_host(domain):
        return "warn", f"Skipped: {domain} is a demo domain that isn't on the internet."
    url = f"https://{domain}/.well-known/alexa-connector.json"
    try:
        hosted = httpx.get(url, timeout=3).raise_for_status().json()
    except Exception:  # noqa: BLE001 - unreachable, not JSON, 404...: all mean "not hosted"
        return "err", f"Couldn't fetch {url}. Host the manifest there (without the private block)."
    public = {k: v for k, v in m.items() if k != "private"}
    if hosted != public:
        return "err", f"{url} doesn't match the upload."
    return "ok", f"{url} matches the upload with the private block excluded."


def _check_domain(m: dict) -> tuple[str, str]:
    domain = ((m.get("publisher") or {}).get("domain") or "").lower()
    host = _host(((m.get("openapi") or {}).get("servers") or [{}])[0].get("url"))
    if not host or not domain:
        return "err", "API server or publisher domain is missing."
    if host == domain or host.endswith("." + domain):
        return "ok", f"{host} belongs to {domain}."
    if is_local_host(host):
        return "warn", f"{host} is a local mock host; on the internet it must be under {domain}."
    return "err", f"{host} isn't under {domain}."


def _check_voice(m: dict) -> tuple[str, str]:
    problems = []
    tools = tools_from_manifest(m)
    for t in tools:
        missing = []
        if not t["description"]:
            missing.append("description")
        if len(t["example_phrases"]) < 2:
            missing.append("2 example phrases")
        if not t["speakable_response"]:
            missing.append("speakableResponse")
        if missing:
            problems.append(f"{t['name']}: {', '.join(missing)}")
    if problems:
        return "err", "Missing " + "; ".join(problems) + "."
    return "ok", (f"{len(tools)} of {len(tools)} endpoints have a description, at least 2 example "
                  "phrases and a speakableResponse.")


def _check_confirm(m: dict) -> tuple[str, str]:
    writes = [t for t in tools_from_manifest(m) if not t["read_only"] or t["side_effect"] != "none"]
    bad = [t["name"] for t in writes if not (t["requires_confirmation"] and t["confirmation_prompt"])]
    if bad:
        return "err", f"{', '.join(bad)} must set requiresConfirmation: true and a confirmationPrompt."
    if not writes:
        return "ok", "No write endpoints."
    names = ", ".join(f"{t['name']} ({t['side_effect']})" for t in writes)
    return "ok", names + (" asks" if len(writes) == 1 else " ask") + " before acting."


def _check_limit(m: dict) -> tuple[str, str]:
    n = len(operations(m))
    if n > MAX_ENDPOINTS:
        return "err", f"{n} endpoints; split the service or remove some."
    return "ok", f"{n} endpoint{'s' if n != 1 else ''}."


_RUNNERS = {"schema": _check_schema, "openapi": _check_openapi, "https": _check_https,
            "hosted": _check_hosted, "domain": _check_domain, "voice": _check_voice,
            "confirm": _check_confirm, "limit": _check_limit}


def run_checks(manifest: dict) -> dict:
    """{passed, checks: [{id, title, status: ok|warn|err, message}], tools, version}.
    Warnings don't fail the report; they mark what only the local demo allows."""
    checks = []
    schema_ok = isinstance(manifest, dict) and _check_schema(manifest)[0] == "ok"
    for check_id, title in CHECKS:
        if not isinstance(manifest, dict):
            status, message = "err", "The upload isn't a JSON object."
        elif check_id != "schema" and not schema_ok and check_id in {"openapi", "voice", "confirm"} \
                and not isinstance(manifest.get("openapi"), dict):
            status, message = "err", "Needs a valid openapi block first."
        else:
            try:
                status, message = _RUNNERS[check_id](manifest)
            except Exception as exc:  # noqa: BLE001 - a malformed manifest gets a report, not a 500
                status, message = "err", f"Couldn't check: {exc}"
        checks.append({"id": check_id, "title": title, "status": status, "message": message})
    try:
        tools = tools_from_manifest(manifest) if isinstance(manifest, dict) else []
    except Exception:  # noqa: BLE001 - same: the checks above already explain what is wrong
        tools = []
    info = ((manifest.get("openapi") or {}).get("info") or {}) if isinstance(manifest, dict) else {}
    return {"passed": all(c["status"] != "err" for c in checks), "checks": checks, "tools": tools,
            "version": str(info.get("version") or "")}
