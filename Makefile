.PHONY: dev test lint mocks db

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
