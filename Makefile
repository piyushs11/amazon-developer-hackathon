.PHONY: dev test lint mocks db seed

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
	docker compose up -d postgres

# Load the catalog's services into the registry (Postgres). Same as the `seed` service in compose.
seed:
	docker compose up -d --wait postgres catalog
	python -m backend.app.db.registry.seed
