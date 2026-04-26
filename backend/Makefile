install:
	uv sync

dev:
	uv run langgraph dev --no-browser --no-reload --n-jobs-per-worker 10

gateway:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8100

test:
	PYTHONPATH=. uv run pytest tests/ -v

lint:
	uvx ruff check .
	uvx ruff format --check .

format:
	uvx ruff check . --fix && uvx ruff format .

# ── Identity subsystem (M1) ────────────────────────────────────────────────
db-upgrade:
	PYTHONPATH=. uv run alembic upgrade head

db-downgrade-one:
	PYTHONPATH=. uv run alembic downgrade -1

identity-bootstrap:
	PYTHONPATH=. uv run python -m app.gateway.identity.cli bootstrap

# Create (or heal) a tenant's on-disk directory tree with 0700 perms.
# Usage: make identity-dirs TENANT_ID=<id> [WORKSPACE_ID=<id>]
identity-dirs:
	@if [ -z "$(TENANT_ID)" ]; then echo "Usage: make identity-dirs TENANT_ID=<id> [WORKSPACE_ID=<id>]"; exit 1; fi
	PYTHONPATH=. uv run python -m app.gateway.identity.storage.cli \
		--tenant-id $(TENANT_ID) \
		$(if $(WORKSPACE_ID),--workspace-id $(WORKSPACE_ID))

identity-test:
	PYTHONPATH=. IDENTITY_TEST_BACKEND=on uv run pytest tests/identity/ -v

# Generate (or reuse) the RS256 keypair used by M2 auth. Writes to
# $DEERFLOW_HOME/_system/ by default; respects DEERFLOW_JWT_*_KEY_PATH.
identity-keys:
	PYTHONPATH=. uv run python -c "from app.gateway.identity.auth.jwt import ensure_rsa_keypair; from app.gateway.identity.settings import get_identity_settings; s = get_identity_settings(); priv, pub = ensure_rsa_keypair(s.jwt_private_key_path, s.jwt_public_key_path); print(f'private: {s.jwt_private_key_path}'); print(f'public:  {s.jwt_public_key_path}')"

# ── M7 Migration (legacy single-tenant → multi-tenant layout) ──────────────
# Dry-run never writes. Real migrations need the DB running; use --no-db for
# air-gapped rehearsals on a tmp DEER_FLOW_HOME.
identity-migrate-dry:
	PYTHONPATH=. uv run python ../scripts/migrate_to_multitenant.py --dry-run

identity-migrate-apply:
	PYTHONPATH=. uv run python ../scripts/migrate_to_multitenant.py --apply

# Rollback takes the report written by a prior --apply run:
#   make identity-migrate-rollback REPORT=backend/.deer-flow/_system/migration_report_....json
identity-migrate-rollback:
	@if [ -z "$(REPORT)" ]; then echo "Usage: make identity-migrate-rollback REPORT=<path>"; exit 1; fi
	PYTHONPATH=. uv run python ../scripts/migrate_to_multitenant.py --rollback --report $(REPORT)
