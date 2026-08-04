.DEFAULT_GOAL := help

.PHONY: bootstrap build check clean dev-down dev-logs dev-up e2e format help test test-e2e test-integration test-unit

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest

help:
	@echo "bootstrap        Create the pinned Python development environment"
	@echo "check            Run formatting, lint, types, and 100% coverage gate"
	@echo "build            Run every gate, browser E2E, and build local images"
	@echo "dev-up           Start HA, fake Poolside, Loki, Alloy, and Grafana"
	@echo "dev-down         Stop the local stack and delete only its named test volumes"
	@echo "e2e              Run browser UI-to-service E2E in isolated Docker"

bootstrap:
	python3.14 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install --editable '.[test]'

format:
	.venv/bin/ruff format .
	.venv/bin/ruff check . --fix

test-unit:
	$(PYTEST) -m unit

test-integration:
	$(PYTEST) -m integration

test-e2e:
	$(PYTEST) -m e2e

test:
	$(PYTEST) --cov=custom_components.poolside --cov-branch --cov-report=term-missing

check:
	.venv/bin/ruff format --check .
	.venv/bin/ruff check .
	.venv/bin/mypy custom_components/poolside tests
	$(MAKE) test
	docker compose config --quiet

e2e:
	./scripts/e2e.sh

build: check e2e
	docker compose build fake-poolside e2e

dev-up:
	docker compose --profile observability up --build --detach fake-poolside home-assistant loki alloy grafana

dev-logs:
	docker compose logs --follow home-assistant fake-poolside alloy loki grafana

dev-down:
	docker compose --profile observability down --volumes

clean:
	docker compose --profile observability down --volumes
	$(PYTHON) -m coverage erase
