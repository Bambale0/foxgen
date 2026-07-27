.PHONY: install lock lock-check lint format typecheck test coverage ci up down migrate

install:
	python -m pip install --requirement requirements.lock
	python -m pip install --no-deps --editable .
	python -m pip check

lock:
	python -m pip install pip-tools==7.6.0
	CUSTOM_COMPILE_COMMAND="make lock" pip-compile pyproject.toml \
		--extra dev \
		--resolver backtracking \
		--allow-unsafe \
		--strip-extras \
		--output-file requirements.lock

lock-check:
	python scripts/check_lock.py

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy src

test:
	pytest -q

coverage:
	pytest -q --cov=foxgen --cov-report=term-missing --cov-report=xml:coverage.xml

ci: lock-check lint typecheck coverage

up:
	docker compose up --build

down:
	docker compose down

migrate:
	alembic upgrade head
