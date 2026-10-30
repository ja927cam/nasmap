SHELL := /bin/bash
COMPOSE ?= docker compose
PROD_COMPOSE ?= docker compose -f docker-compose.yml -f docker-compose.prod.yml
REGION ?= cambridge
OSM_PBF ?= data/osm/$(REGION)-latest.osm.pbf

.PHONY: help env up down restart logs ps migrate backup restore download-osm crop-osm import-osm generate-tiles update-osm test lint fmt shell db-shell api-shell build clean sample

help:
	@echo "Strata targets:"
	@echo "  make env              create .env from .env.example (if missing)"
	@echo "  make up               build and start the stack"
	@echo "  make down             stop the stack"
	@echo "  make logs             tail logs"
	@echo "  make migrate          apply SQL migrations"
	@echo "  make backup           database + uploads backup"
	@echo "  make restore FILE=... restore a backup"
	@echo "  make download-osm     download REGION pbf from Geofabrik"
	@echo "  make crop-osm         crop a PBF to BBOX (osmium extract)"
	@echo "  make import-osm       import REGION pbf into PostGIS"
	@echo "  make update-osm       download + re-import + regenerate tiles"
	@echo "  make generate-tiles   build local vector tiles (REGION=...)"
	@echo "  make test             run API tests"
	@echo "  make lint             run linters"

env:
	@test -f .env || (cp .env.example .env && echo "Created .env - edit secrets before production use")

up: env
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

migrate:
	$(COMPOSE) exec -T api python -m app.migrate

backup:
	./scripts/backup.sh

restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/..." && exit 1)
	./scripts/restore.sh "$(FILE)"

download-osm:
	./scripts/download-osm.sh "$(REGION)"

crop-osm:
	./scripts/crop-osm.sh "$(INPUT)" "$(OUTPUT)"

import-osm:
	./scripts/import-osm.sh "$(REGION)"

generate-tiles:
	./scripts/generate-tiles.sh "$(REGION)"

update-osm:
	./scripts/update-osm.sh "$(REGION)"

test:
	$(COMPOSE) --profile test up -d db-test
	$(COMPOSE) run --rm --no-deps \
		-e DATABASE_URL=postgresql+asyncpg://nasmap:nasmap@db-test:5432/nasmap_test \
		-e TEST_DATABASE_URL=postgresql+asyncpg://nasmap:nasmap@db-test:5432/nasmap_test \
		-e UPLOAD_DIR=/tmp/nasmap-test/uploads \
		-e TESSERA_CACHE_DIR=/tmp/nasmap-test/tessera \
		-e TILES_DIR=/tmp/nasmap-test/tiles \
		-e RATE_LIMITING_ENABLED=false \
		-e TESSERA_ENABLED=false \
		-e JSON_LOGS=false \
		-e ENV=test \
		api pytest -q

lint:
	$(COMPOSE) run --rm --no-deps api ruff check app tests
	cd web && npm run lint && npm run typecheck

fmt:
	$(COMPOSE) run --rm --no-deps api ruff format app tests

shell:
	$(COMPOSE) exec api bash

db-shell:
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-nasmap} -d $${POSTGRES_DB:-nasmap}

clean: down
	$(COMPOSE) down -v --remove-orphans
