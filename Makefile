.DEFAULT_GOAL := help

.PHONY: bootstrap build check clean dev-down dev-logs dev-up e2e format help package package-artifact test test-e2e test-integration test-unit

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
VERSION := $(shell sed -n 's/.*"version": "\([^"]*\)".*/\1/p' custom_components/poolside/manifest.json)
ARTIFACT_NAME := poolside-$(VERSION).zip
ARTIFACT := dist/$(ARTIFACT_NAME)

help:
	@echo "bootstrap        Create the pinned Python development environment"
	@echo "check            Run formatting, lint, types, and 100% coverage gate"
	@echo "build            Run every gate, package the integration, and build local images"
	@echo "package          Run every gate and create the installable release ZIP"
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

package: check e2e package-artifact

package-artifact:
	mkdir -p dist
	git diff --quiet
	git diff --cached --quiet
	git archive --format=zip --prefix=poolside/ --output=$(ARTIFACT) HEAD:custom_components/poolside
	unzip -t $(ARTIFACT)
	cd dist && shasum -a 256 $(ARTIFACT_NAME) > $(ARTIFACT_NAME).sha256

build: package
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
