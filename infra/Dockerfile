# One image for the API + MCP gateway (build from the repo root:
#   docker build -f infra/Dockerfile .)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# jq: backend/app/codegen/create_folders.sh needs it to generate tool bundles when a service is
# published (without it, publish fails at the "codegen" step with "jq is required").
RUN apt-get update \
 && apt-get install -y --no-install-recommends jq \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY backend ./backend
COPY contracts ./contracts
COPY runtime ./runtime
# Editable install keeps the source (and contracts/fixtures) at /app.
RUN pip install --no-cache-dir -e .

RUN useradd --create-home app && mkdir -p /app/.cache /app/generated && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
