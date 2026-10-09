#!/usr/bin/env bash
# MCP Bridge — Day 0 skeleton
# Usage: bash create_skeleton.sh [target_dir]   (default: ./mcp-bridge)
# Safe to re-run: never overwrites a file that already exists.
set -euo pipefail

ROOT="${1:-mcp-bridge}"
mkdir -p "$ROOT"
cd "$ROOT"

# ---------- helpers ----------
# mkfile <path> [content]  -> creates file only if missing
mkfile() {
  local path="$1"; shift || true
  mkdir -p "$(dirname "$path")"
  if [ ! -e "$path" ]; then
    printf '%s\n' "${1:-}" > "$path"
  fi
}

# pkg <dir> <owner> <purpose>  -> python package with __init__.py + README.md
pkg() {
  local dir="$1" owner="$2" purpose="$3"
  mkdir -p "$dir"
  mkfile "$dir/__init__.py" ""
  mkfile "$dir/README.md" "# $(basename "$dir")

**Owner:** $owner

$purpose

## Input
TODO

## Output
TODO"
}

# folder <dir> <owner> <purpose>  -> non-python folder with README.md
folder() {
  local dir="$1" owner="$2" purpose="$3"
  mkdir -p "$dir"
  mkfile "$dir/README.md" "# $(basename "$dir")

**Owner:** $owner

$purpose"
}

# ---------- root files ----------
mkfile README.md "# MCP Bridge

Turns a service's endpoint spec into a hosted MCP server for Alexa+.

See \`docs/plan/\` for the team plan, contracts and integration map.

## Quick start
\`\`\`bash
cp .env.example .env
make dev
\`\`\`"

mkfile CONTRIBUTING.md "# Contributing

- Branch from \`main\`: \`feat/<lane>-<short-name>\` (lanes: catalog, codegen, auth, ui)
- No direct commits to \`main\`
- Small PRs (~300 lines), 1 review, squash merge
- Rebase on \`main\` daily
- Stay in your own folders (see CODEOWNERS)
- \`contracts/\` changes: separate PR, all 4 approve, update fixtures in the same PR
- Never commit \`.env\`, tokens or secrets"

mkfile .gitignore "# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
*.egg-info/

# Node
node_modules/
.next/
out/

# Env and secrets
.env
.env.*
!.env.example

# Generated bundles
generated/

# OS / editor
.DS_Store
.idea/
.vscode/"

mkfile .env.example "# ---- shared ----
MODE=local

# ---- Dev 1: catalog + registry ----
DATABASE_URL=postgresql://mcpbridge:mcpbridge@localhost:5432/mcpbridge
CATALOG_URL=http://localhost:9200

# ---- Dev 2: codegen + storage ----
GENERATED_DIR=./generated

# ---- Dev 3: auth + deploy ----
TOKEN_PROVIDER=fake
TOKEN_ENC_KEY=change-me-local-only
OAUTH_STATE_SECRET=change-me-local-only

# ---- Dev 4: api + frontend ----
API_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000"

mkfile Makefile ".PHONY: dev test lint mocks db

dev:
	docker compose up -d
	uvicorn backend.app.main:app --reload --port 8000

test:
	pytest -q

lint:
	ruff check .

mocks:
	docker compose up -d demo-api oauth catalog

db:
	docker compose up -d postgres"

mkfile pyproject.toml "[project]
name = \"mcp-bridge\"
version = \"0.1.0\"
requires-python = \">=3.12\"
dependencies = [
  \"fastapi\",
  \"uvicorn\",
  \"pydantic>=2\",
  \"httpx\",
  \"jinja2\",
  \"psycopg[binary]\",
  # \"mcp==<PIN ON DAY 0>\",
]

[project.optional-dependencies]
dev = [\"pytest\", \"pytest-asyncio\", \"respx\", \"ruff\"]

[tool.pytest.ini_options]
testpaths = [\"tests\", \"backend/tests\"]

[tool.ruff]
line-length = 100"

mkfile docker-compose.yml "services:
  # ---- Dev 1 ----
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: mcpbridge
      POSTGRES_PASSWORD: mcpbridge
      POSTGRES_DB: mcpbridge
    ports: [\"5432:5432\"]

  # catalog:            # Dev 1 — mock-services/catalog on :9200
  # ---- Dev 3 ----
  # demo-api:           # Dev 3 — mock-services/demo-api on :9000
  # oauth:              # Dev 3 — mock-services/oauth on :9100"

# ---------- .github ----------
mkfile .github/CODEOWNERS "# Replace @dev1..@dev4 with GitHub usernames
/contracts/                    @dev1 @dev2 @dev3 @dev4
/backend/app/resolver/         @dev1
/backend/app/spec/             @dev1
/backend/app/mapper/           @dev1
/backend/app/db/registry/      @dev1
/mock-services/catalog/        @dev1
/backend/app/codegen/          @dev2
/backend/app/pipeline/         @dev2
/backend/app/storage/          @dev2
/runtime/client.py             @dev2
/backend/app/auth/             @dev3
/backend/app/deploy/           @dev3
/runtime/tokens.py             @dev3
/runtime/adapter.py            @dev3
/mock-services/demo-api/       @dev3
/mock-services/oauth/          @dev3
/infra/                        @dev3
/backend/app/api/              @dev4
/backend/app/core/             @dev4
/backend/app/main.py           @dev4
/frontend/                     @dev4
/simulator/                    @dev4
/docs/                         @dev4
/.github/                      @dev4"

mkfile .github/pull_request_template.md "## What
<!-- one or two lines -->

## Lane
- [ ] catalog (Dev 1)  - [ ] codegen (Dev 2)  - [ ] auth/deploy (Dev 3)  - [ ] ui/api (Dev 4)

## Checklist
- [ ] Rebased on main
- [ ] Only touched my folders (or allowed shared files)
- [ ] Tests pass
- [ ] Contract/fixture changes are in a separate approved PR
- [ ] No secrets committed"

mkfile .github/workflows/ci.yml "name: ci
on: [pull_request, push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -e '.[dev]'
      - run: ruff check .
      - run: pytest -q"

# ---------- contracts (shared) ----------
pkg contracts "All 4 devs (changes need all approvals)" "Shared Pydantic models (C1–C7) and interfaces."
mkfile contracts/models.py "\"\"\"Shared models C1–C7. See docs/plan/00-overview-and-contracts.md.\"\"\"
# TODO Day 0: ServiceSpec, MappedService, CallContext, ToolResult,
#             DeployRequest, DeployResult, RegisterResult, StepError,
#             GenerationResult, PublishResult"
mkfile contracts/interfaces.py "\"\"\"Shared Protocols. See docs/plan/00-overview-and-contracts.md.\"\"\"
# TODO Day 0: TokenProvider, Deployer, Registrar, Storage"
mkfile contracts/fixtures/spec.demo_bistro.json "{}"
mkfile contracts/fixtures/mapped.demo_bistro.json "{}"
mkfile contracts/fixtures/api_examples.json "{}"
mkfile contracts/fixtures/bundle.demo_bistro/manifest.json "{}"
mkfile contracts/fixtures/bundle.demo_bistro/server.py "# TODO Day 0: hand-written reference server"
mkfile contracts/fixtures/bundle.demo_bistro/endpoints/__init__.py ""
mkfile contracts/fixtures/bundle.demo_bistro/endpoints/get_order_status.py "# TODO Day 0: reference endpoint (C3 shape)"
mkfile contracts/fixtures/bundle.demo_bistro/requirements.txt "# pinned versions"

# ---------- backend ----------
pkg backend "All" "FastAPI backend."
pkg backend/app "Dev 4" "Application package."
mkfile backend/app/main.py "from fastapi import FastAPI

app = FastAPI(title=\"MCP Bridge\")


@app.get(\"/health\")
def health() -> dict:
    return {\"status\": \"ok\"}"

pkg backend/app/core       "Dev 4" "Config, logging, and wiring.py (picks fake vs real by MODE)."
mkfile backend/app/core/config.py "# TODO: settings loaded from env (MODE, DATABASE_URL, ...)"
mkfile backend/app/core/wiring.py "\"\"\"Single place that picks fake or real implementations by MODE.\"\"\"
# def get_spec_source(): ...    # Dev 1
# def get_mapper(): ...         # Dev 1
# def get_storage(): ...        # Dev 2
# def get_token_provider(): ... # Dev 3
# def get_deployer(): ...       # Dev 3
# def get_registrar(): ...      # Dev 3"

pkg backend/app/api        "Dev 4" "REST routes (contract C7)."
pkg backend/app/resolver   "Dev 1" "Step 0: service name/URL -> service_uuid."
pkg backend/app/spec       "Dev 1" "Step 1: parse + validate catalog spec -> ServiceSpec (C1)."
pkg backend/app/mapper     "Dev 1" "Step 2: ServiceSpec -> MappedService (C2)."
pkg backend/app/db         "Dev 1 / Dev 3" "Database access."
pkg backend/app/db/registry "Dev 1" "service_registry + endpoint_registry repositories."
pkg backend/app/db/mapping  "Dev 3" "user_service_mapping repository."
pkg backend/app/codegen    "Dev 2" "Sanitizer, Jinja2 templates, bundle writer (C3)."
mkdir -p backend/app/codegen/templates
pkg backend/app/storage    "Dev 2" "Storage interface: local folder and S3."
pkg backend/app/pipeline   "Dev 2" "generate_service() and publish() (C6)."
pkg backend/app/auth       "Dev 3" "OAuth A1–A5, token vault, refresh."
pkg backend/app/deploy     "Dev 3" "Deployer + Registrar (local, aws, mock) (C5)."
pkg backend/tests          "All" "Unit tests, one subfolder per lane."
for lane in catalog codegen auth api; do mkfile "backend/tests/$lane/__init__.py" ""; done

# ---------- runtime (imported by generated servers) ----------
pkg runtime "Dev 2 / Dev 3" "Code imported by every generated server."
mkfile runtime/client.py  "\"\"\"Dev 2: call_api() and ToolResult (C4).\"\"\""
mkfile runtime/tokens.py  "\"\"\"Dev 3: TokenProvider implementations (C4).\"\"\""
mkfile runtime/adapter.py "\"\"\"Dev 3: run a bundle locally or as a Lambda handler.\"\"\""

# ---------- mock services ----------
folder mock-services          "Dev 1 / Dev 3" "Local fake services used for development and demo."
folder mock-services/catalog  "Dev 1" "Serves catalog spec JSON on :9200."
mkdir -p mock-services/catalog/specs
folder mock-services/demo-api "Dev 3" "Fake Demo Bistro API on :9000."
folder mock-services/oauth    "Dev 3" "Fake OAuth authorize/token on :9100."

# ---------- other top-level ----------
folder frontend  "Dev 4" "Next.js app (S1, S2a, S2b, S2c). Initialise with create-next-app."
folder simulator "Dev 4" "Alexa+ simulator: MCP client + call trace."
folder infra     "Dev 3 (Dev 1 for data stores)" "AWS setup scripts / IaC."
folder docs      "Dev 4" "README material, architecture, demo script."
mkdir -p docs/plan
pkg tests        "All" "Cross-lane tests."
pkg tests/integration "All" "One test per seam (see docs/plan/01-integration-map.md)."
mkdir -p generated && mkfile generated/.gitkeep ""

echo "Skeleton created in: $(pwd)"