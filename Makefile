.PHONY: install lint format typecheck test ci up down migrate

install:
	python -m pip install -e '.[dev]'

lint:
	ruff check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy src

test:
	pytest -q

ci: lint typecheck test

up:
	docker compose up --build

down:
	docker compose down

migrate:
	alembic upgrade head
