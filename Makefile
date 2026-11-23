.DEFAULT_GOAL := help

UV ?= uv
PYTHON ?= 3.11

.PHONY: help doctor setup test quality lint format-check typecheck up migrate seed-fixture db-shell down init-local-secrets refresh status dbt-build dbt-docs orchestration-up orchestration-down orchestration-status test-integration test-dashboard security backup restore-test reset-data airflow-dag-check

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## / - /'

doctor: ## Report local tool availability (does not install tools)
	@printf 'OS: '; uname -srm
	@printf 'Shell: %s\n' "$${SHELL:-unknown}"
	@$(UV) --version
	@$(UV) python find $(PYTHON)
	@docker --version 2>/dev/null || echo 'Docker unavailable'
	@docker compose version 2>/dev/null || echo 'Docker Compose unavailable'

setup: ## Install the locked application and development dependencies
	$(UV) sync --locked --extra dev --extra db --extra api --extra dashboard --extra notebook

test: ## Run unit tests
	$(UV) run --locked --extra dev --extra db --extra api --extra dashboard pytest --basetemp=.test-tmp

lint: ## Run Ruff lint
	$(UV) run --locked --extra dev ruff check .

format-check: ## Check formatting
	$(UV) run --locked --extra dev ruff format --check .

typecheck: ## Run mypy
	$(UV) run --locked --extra dev --extra db --extra api --extra dashboard mypy src

quality: lint format-check typecheck test ## Run all local quality checks

up: ## Start the local PostgreSQL, API, and dashboard services
	docker compose up --build -d

migrate: ## Apply database migrations
	@set -a; . ./.env; set +a; $(UV) run --locked --extra db alembic upgrade head

seed-fixture: ## Insert the canonical synthetic fixture through the API
	@set -a; . ./.env; set +a; $(UV) run --locked --extra api python -m survivallab.seed

db-shell: ## Open a psql shell in the local database container
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

down: ## Stop services without deleting persistent volumes
	docker compose down

init-local-secrets: ## Create an ignored local .env with generated credentials
	@test ! -e .env || { echo '.env already exists; refusing to overwrite' >&2; exit 1; }
	@umask 077; \
	  dbpass=$$(openssl rand -hex 24); ingest=$$(openssl rand -hex 24); \
	  readpass=$$(openssl rand -hex 24); pipeline=$$(openssl rand -hex 24); \
	  analytics=$$(openssl rand -hex 24); key=$$(openssl rand -hex 32); \
	  airflowdb=$$(openssl rand -hex 24); airflowadmin=$$(openssl rand -hex 24); \
	  airflowjwt=$$(openssl rand -hex 32); \
	  fernet=$$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'); \
	  { printf 'POSTGRES_DB=survivallab\nPOSTGRES_USER=survivallab_migrator\nPOSTGRES_PASSWORD=%s\n' "$$dbpass"; \
	    printf 'INGEST_PASSWORD=%s\nREAD_PASSWORD=%s\nPIPELINE_PASSWORD=%s\nANALYTICS_PASSWORD=%s\n' "$$ingest" "$$readpass" "$$pipeline" "$$analytics"; \
	    printf 'DATABASE_URL=postgresql+psycopg://survivallab_migrator:%s@127.0.0.1:5432/survivallab\n' "$$dbpass"; \
	    printf 'INGEST_DATABASE_URL=postgresql+psycopg://survivallab_ingest:%s@127.0.0.1:5432/survivallab\n' "$$ingest"; \
	    printf 'READ_DATABASE_URL=postgresql+psycopg://survivallab_reader:%s@127.0.0.1:5432/survivallab\n' "$$readpass"; \
	    printf 'PIPELINE_DATABASE_URL=postgresql+psycopg://survivallab_pipeline:%s@127.0.0.1:5432/survivallab\n' "$$pipeline"; \
	    printf 'ANALYTICS_DATABASE_URL=postgresql+psycopg://survivallab_analytics:%s@127.0.0.1:5432/survivallab\n' "$$analytics"; \
	    printf 'API_KEY=%s\nAPI_BASE_URL=http://127.0.0.1:8000\nSTREAMLIT_API_URL=http://127.0.0.1:8000\n' "$$key"; \
	    printf 'AIRFLOW_DB_NAME=survivallab_airflow\nAIRFLOW_DB_USER=survivallab_airflow\nAIRFLOW_DB_PASSWORD=%s\n' "$$airflowdb"; \
	    printf 'AIRFLOW_FERNET_KEY=%s\nAIRFLOW_API_JWT_SECRET=%s\nAIRFLOW_ADMIN_USERNAME=survivallab-admin\nAIRFLOW_ADMIN_PASSWORD=%s\n' "$$fernet" "$$airflowjwt" "$$airflowadmin"; \
	    printf 'AIRFLOW_API_URL=http://127.0.0.1:8081\n'; \
	  } > .env

refresh: ## Refresh and publish the aggregate model through the API
	@set -a; . ./.env; set +a; curl --fail --silent --show-error -X POST -H "X-API-Key: $$API_KEY" "$${API_BASE_URL}/pipeline/refresh"

status: ## Show API pipeline/model status
	@set -a; . ./.env; set +a; curl --fail --silent --show-error "$${API_BASE_URL}/pipeline/status"

dbt-build: ## Build and test dbt analytics models
	@set -a; . ./.env; set +a; DBT_PROFILE_HOST=127.0.0.1 DBT_PROFILE_PORT=5432 DBT_PROFILE_USER=survivallab_analytics DBT_PROFILE_PASSWORD="$$ANALYTICS_PASSWORD" DBT_PROFILE_DATABASE="$$POSTGRES_DB" uv run --project dbt --locked dbt build --project-dir dbt --profiles-dir dbt

dbt-docs: ## Generate dbt docs as local command output
	@set -a; . ./.env; set +a; DBT_PROFILE_HOST=127.0.0.1 DBT_PROFILE_PORT=5432 DBT_PROFILE_USER=survivallab_analytics DBT_PROFILE_PASSWORD="$$ANALYTICS_PASSWORD" DBT_PROFILE_DATABASE="$$POSTGRES_DB" uv run --project dbt --locked dbt docs generate --project-dir dbt --profiles-dir dbt

test-integration: ## Run tests requiring a configured local PostgreSQL service
	@test -n "$${SURVIVALLAB_TEST_DATABASE_URL:-}" || { echo 'Set SURVIVALLAB_TEST_DATABASE_URL to a disposable database' >&2; exit 2; }
	$(UV) run --locked --extra dev --extra db --extra api pytest --basetemp=.test-tmp -m integration

test-dashboard: ## Run Streamlit client and UI tests
	$(UV) run --locked --extra dev --extra api --extra dashboard pytest tests/test_dashboard.py

orchestration-up: ## Start optional Airflow services (requires at least 4 GiB Docker memory)
	@docker info --format '{{.MemTotal}}' | awk '{ if ($$1 < 4294967296) { print "Docker needs at least 4 GiB for Airflow" > "/dev/stderr"; exit 1 } }'
	docker compose --profile orchestration up -d

orchestration-down: ## Stop optional Airflow services without removing volumes
	docker compose --profile orchestration stop airflow-api airflow-scheduler airflow-dag-processor airflow-triggerer airflow-db

orchestration-status: ## Show optional Airflow service status
	docker compose --profile orchestration ps

airflow-dag-check: ## Parse the Airflow 3 DAG inside the pinned official image
	docker run --rm --entrypoint python -e PYTHONDONTWRITEBYTECODE=1 -v "$(PWD)/airflow/dags:/opt/airflow/dags:ro" apache/airflow:3.4.0-python3.11@sha256:be92e15d57c5be726fc39a91cd09cce8f7488483b67979e0fb74c1a2c7cfb4e2 -c 'from airflow.models import DagBag; bag=DagBag("/opt/airflow/dags"); assert not bag.import_errors, bag.import_errors; assert "survivallab_refresh" in bag.dags; print("Airflow DAG parsed")'

security: ## Run dependency and secret scans
	@set -eu; \
	  requirements=.security-requirements.txt; \
	  trap 'rm -f "$$requirements"' EXIT; \
	  $(UV) export --locked --all-extras --all-groups --no-emit-project --format requirements-txt > "$$requirements"; \
	  $(UV) run --locked --extra dev pip-audit --requirement "$$requirements"; \
	  $(UV) export --project dbt --locked --no-emit-project --format requirements-txt > "$$requirements"; \
	  $(UV) run --locked --extra dev pip-audit --requirement "$$requirements"; \
	  $(UV) export --project airflow --locked --no-emit-project --format requirements-txt > "$$requirements"; \
	  $(UV) run --locked --extra dev pip-audit --requirement "$$requirements"
	@if test -d .git; then \
	  docker run --rm -v "$(PWD):/repo:ro" zricethezav/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f detect --source=/repo --redact; \
	else \
	  docker run --rm -v "$(PWD):/repo:ro" zricethezav/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f detect --source=/repo --no-git --config=/repo/.gitleaks-local.toml --redact; \
	fi

BACKUP ?= backups/survivallab-$(shell date -u +%Y%m%dT%H%M%SZ).dump

backup: ## Create a custom-format database backup under ignored backups/
	@mkdir -p backups && chmod 700 backups
	docker compose exec -T db sh -c 'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -Fc' > "$(BACKUP)"
	@chmod 600 "$(BACKUP)"
	@printf 'Backup created: %s\n' "$(BACKUP)"

restore-test: ## Restore BACKUP into an isolated scratch database and verify tables
	@test -n "$(BACKUP)" -a -s "$(BACKUP)" || { echo 'Set BACKUP to an existing custom-format dump' >&2; exit 2; }
	@set -eu; \
	  scratch="survivallab_restore_$$(date -u +%Y%m%d%H%M%S)_$$$$"; \
	  cleanup() { docker compose exec -T db sh -c 'dropdb --if-exists -U "$$POSTGRES_USER" "$$1"' sh "$$scratch" >/dev/null; }; \
	  trap cleanup EXIT; \
	  docker compose exec -T db sh -c 'createdb -U "$$POSTGRES_USER" "$$1"' sh "$$scratch"; \
	  docker compose exec -T db sh -c 'pg_restore --no-owner --no-acl -U "$$POSTGRES_USER" -d "$$1"' sh "$$scratch" < "$(BACKUP)"; \
	  tables=$$(docker compose exec -T db sh -c 'psql -At -U "$$POSTGRES_USER" -d "$$1" -c "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname IN (chr(114)||chr(97)||chr(119),chr(109)||chr(101)||chr(116)||chr(97),chr(109)||chr(111)||chr(100)||chr(101)||chr(108))"' sh "$$scratch"); \
	  source_rows=$$(docker compose exec -T db sh -c 'psql -At -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "SELECT count(*) FROM raw.observations"'); \
	  restored_rows=$$(docker compose exec -T db sh -c 'psql -At -U "$$POSTGRES_USER" -d "$$1" -c "SELECT count(*) FROM raw.observations"' sh "$$scratch"); \
	  test "$$tables" -ge 6 || { echo "restore contained only $$tables application tables" >&2; exit 1; }; \
	  test "$$source_rows" = "$$restored_rows" || { echo 'restored observation count does not match source' >&2; exit 1; }; \
	  printf 'Restore verified: %s application tables and %s observation rows\n' "$$tables" "$$restored_rows"

reset-data: ## Destructively clear application rows after explicit confirmation
	@test "$(CONFIRM_RESET)" = YES || { echo 'Refusing destructive reset; rerun with CONFIRM_RESET=YES' >&2; exit 2; }
	docker compose exec -T db sh -c 'psql --set=ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "TRUNCATE TABLE raw.observations, meta.snapshots, meta.snapshot_members, meta.pipeline_runs, model.candidate_fits, model.active_model RESTART IDENTITY CASCADE"'

