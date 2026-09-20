PORT ?= 8000

.PHONY: help run format check fix openapi up down build logs

help:
	@echo "make run     - run the API locally (uvicorn --reload on $(PORT))"
	@echo "make format  - format Python with ruff"
	@echo "make check   - lint Python with ruff"
	@echo "make fix     - lint and auto-fix with ruff"
	@echo "make openapi - regenerate openapi.json"
	@echo "make up      - docker compose up --build (detached)"
	@echo "make down    - docker compose down"
	@echo "make build   - docker build the image"
	@echo "make logs    - follow container logs"

run:
	uv run uvicorn app.main:app --reload --port $(PORT)

format:
	uv run ruff format .

check:
	uv run ruff check .

fix:
	uv run ruff check --fix .

openapi:
	uv run --no-dev python -c 'import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))' > openapi.json

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker build -t laya-api:latest .

logs:
	docker compose logs -f
