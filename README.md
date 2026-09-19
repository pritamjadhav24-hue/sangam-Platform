# SANGAM / GovOrchestrator

SANGAM is a local prototype for purpose-bound government service orchestration. It includes JWT authentication, PostgreSQL persistence, workflow orchestration, dependency handling, schema mapping, entity/conflict review, notifications, and audit correlation.

The production-upgrade foundation adds PostgreSQL-backed departments, providers, services, schemes, and scheme requirements. `GET /api/catalog` exposes the configured catalog. Demo users and initial catalog rows are isolated in the development seed modules and are inserted only when the corresponding database tables are empty and seeding is enabled (`SANGAM_SEED_CATALOG=true`).

Integrations use a provider adapter contract with health checks, discovery, submission, status, retrieval, normalization, bounded retries, error categories, correlation IDs, and idempotency keys. REST, SOAP-ready, file/CSV-ready, and webhook-ready implementations can share this contract; the current adapters are sandbox/mock implementations only.

Redis is an explicit, non-authoritative platform dependency. When enabled, it is used only for short-lived catalog metadata caching, rate/coordination primitives, and the generic job queue. PostgreSQL remains authoritative for applications, requirements, dependencies, workflow state, audit, events, notifications, providers, and capabilities. Set `REDIS_ENABLED=false` for local tests or a no-Redis development run; set `REDIS_ENABLED=true` with a valid `REDIS_URL` when Redis is required. An enabled but unavailable Redis instance fails readiness rather than silently degrading.

The worker is started by Compose as a separate process and consumes generic jobs containing job type, correlation ID, application/dependency IDs, attempt, timestamps, status, and a safe payload. The current application path remains synchronous by default so the existing golden path is preserved; provider operations can be moved behind the same queue as handlers are introduced. No credentials or citizen payloads are cached in Redis, and Redis is not exposed on a host port.

Set `ASYNC_PROVIDER_JOBS=true` to route provider dependency retrieval through the durable PostgreSQL-backed job record and Redis transport. The worker claims jobs atomically in PostgreSQL, invokes the configured adapter factory, and lets the existing dependency engine perform the canonical workflow transition and event/audit/notification side effects. `ASYNC_PROVIDER_JOBS=false` retains synchronous compatibility for local tests.

Administrators can inspect safe operational views through `/api/admin/operations/providers`, `/api/admin/operations/worker`, `/api/admin/operations/jobs/summary`, `/api/admin/operations/jobs/recent`, `/api/admin/operations/jobs/dead-letter`, and `/api/admin/operations/jobs/{job_id}`. Dead-letter replay is available at `/api/admin/operations/jobs/{job_id}/replay`; it requires Redis and rolls back the PostgreSQL replay transaction if Redis cannot accept the job. Payloads are intentionally omitted from operational responses.

Provider metadata and capabilities are stored in PostgreSQL. Sensitive runtime values are referenced through environment variables such as `PROVIDER_<ID>_BASE_URL`, `PROVIDER_<ID>_CLIENT_ID`, and `PROVIDER_<ID>_CLIENT_SECRET`. Catalog APIs expose only whether a referenced value is configured, never the value itself. No real government credentials or live government API integrations are included.

To onboard a provider, create its department/provider records, assign a `provider_capabilities` row pointing to the service and requirement code, set the adapter type/protocol and non-secret retry metadata, configure secret references in the deployment environment, then enable the provider. The dependency engine and requirement analyzer discover the capability from PostgreSQL; no provider-specific branch is required. Sandbox implementations use configuration-only handler names and the same adapter factory used by future real integrations.

## Run locally with Docker Compose

Prerequisites:

- Docker Desktop with Compose support

Configure local secrets without committing them:

```text
copy .env.example .env
```

Edit `.env` and replace the placeholder PostgreSQL password, JWT secret, and demo bootstrap passwords. The Compose backend connects to the PostgreSQL service as `postgres`, not to a developer-installed database on `localhost`.

For Compose, use `REDIS_URL=redis://redis:6379/0` (or leave `REDIS_URL` unset so the Compose default is used). The `localhost` value in `.env.example` is for a backend running directly on the host.

Production defaults do not seed demo users or catalog data. For a development/demo environment, explicitly set `SANGAM_SEED_CATALOG=true` and `SANGAM_SEED_DEMO_USERS=true` in `.env`.

Start the complete local stack:

```text
docker compose up --build
```

Open:

- Frontend: http://localhost:5173
- Backend health: http://localhost:8001/

Stop the stack normally with:

```text
docker compose down
```

PostgreSQL data is stored in the named volume `sangam-postgres-data`, so normal shutdown does not remove applications, workflow history, events, notifications, or audit data. The SANGAM admin Demo Reset clears deterministic application/demo state while retaining the database volume. Removing the volume is a separate destructive operation and is not required for normal resets.

The PostgreSQL container is available only on the Compose network; it is not exposed as a public host port. The backend is exposed on host port `BACKEND_PORT` (8001 by default) and the frontend on 5173. Set `VITE_API_BASE_URL` when the frontend must reach a backend at another URL.

## Existing local scripts

Without containers, the existing `run_platform.bat` and `run_platform.sh` scripts start the local backend on `BACKEND_PORT` (8001 by default) and configure Vite to use the matching API URL. Override `BACKEND_PORT` and `VITE_API_BASE_URL` through the environment when needed. The local backend still requires a PostgreSQL `DATABASE_URL` and JWT/bootstrap environment configuration.

## Validation

Database migrations are managed with Alembic:

```text
cd backend
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

Backend tests use the existing Python `unittest` suite:

```text
cd backend
python -m unittest discover -s tests -v
```

Frontend production build:

```text
cd frontend
npm run build
```

Do not place real passwords, JWT secrets, database URLs containing credentials, or access tokens in source control or documentation.

## Deployment readiness

### Configuration and startup order

Required deployment settings are `DATABASE_URL`, `JWT_SECRET`, `CORS_ALLOWED_ORIGINS`, `REDIS_URL` when Redis is enabled, and `SANGAM_ENV`. `JWT_SECRET` must be a high-entropy deployment secret; placeholders in the example files are not valid production values. `ASYNC_PROVIDER_JOBS`, rate-limit settings, and worker identity are optional operational settings. Provider endpoints and credentials are configured by authorized deployment owners through PostgreSQL metadata and environment secret references; no live government credentials or contracts are included here.

For Compose, the startup order is PostgreSQL and Redis health, backend migration-state/configuration validation, worker heartbeat, then frontend. The backend intentionally refuses to start when PostgreSQL is unavailable, Alembic is not at `head`, or production-mode configuration contains demo/local defaults. The worker exits if PostgreSQL or Redis is unavailable and its healthcheck requires a fresh PostgreSQL-backed heartbeat.

Production deployment should use an explicit non-local origin and mode:

```text
copy .env.example .env
# Set SANGAM_ENV=production, replace every placeholder, and provide authorized provider references.
docker compose up -d postgres redis
docker compose run --rm backend alembic upgrade head
docker compose up -d backend worker frontend
docker compose ps
```

The frontend API URL is a build-time value (`VITE_API_BASE_URL`). Set it to the externally reachable backend API before building the frontend image. Do not put JWTs, provider credentials, or database URLs in frontend variables.

### Health, restart, and recovery

- `/health/live` reports process liveness only.
- `/health/ready` checks PostgreSQL migration state, Redis when enabled, and worker availability when Redis jobs are enabled.
- The worker healthcheck verifies PostgreSQL, Redis, and a fresh heartbeat.
- PostgreSQL is authoritative. Redis queues/cache/locks can be rebuilt from PostgreSQL state.
- Restarting the worker reclaims abandoned `RUNNING` provider jobs from PostgreSQL.
- If Redis restarts while PostgreSQL remains available, queued transport messages are rebuilt from durable provider-job state by worker recovery. A disabled/unavailable Redis instance makes async job operations unavailable rather than falsely successful.

Useful checks:

```text
curl http://localhost:8001/health/live
curl http://localhost:8001/health/ready
docker compose logs --no-color backend worker postgres redis frontend
```

### Backup and restore

Back up PostgreSQL using a custom-format dump:

```text
pg_dump --format=custom --file=sangam-$(Get-Date -Format yyyyMMdd-HHmmss).dump "$env:DATABASE_URL"
```

Restore only into a separate test database first; never overwrite the development or production database during validation:

```text
createdb sangam_restore_test
pg_restore --clean --if-exists --dbname="$env:RESTORE_DATABASE_URL" sangam-backup.dump
set ALEMBIC_DATABASE_URL=%RESTORE_DATABASE_URL%
cd backend
alembic current
alembic check
```

Successful `pg_dump` or `pg_restore` is not proof of a usable backup. Validate that the restored database reaches the expected Alembic head, passes application readiness, and can read persisted applications and workflow state. Redis is non-authoritative and is intentionally excluded from backup/restore requirements.

### Demo, sandbox, and provider boundaries

Demo users and catalog seeding require explicit `SANGAM_SEED_DEMO_USERS=true` and `SANGAM_SEED_CATALOG=true`; both must remain disabled in production. Production startup rejects active non-`PRODUCTION` providers and local CORS origins. Mock/sandbox adapters are for development/demo only. Real provider credentials, endpoints, contracts, and authorization remain deployment-owner responsibilities.

### Troubleshooting and known limitations

- `Database schema is at migration ...; run 'alembic upgrade head'`: apply migrations before starting backend/worker.
- Redis readiness failure: verify `REDIS_ENABLED`, `REDIS_URL`, and Redis health; do not switch Redis to an in-memory fallback in deployment.
- Worker `UNAVAILABLE` or `STALE`: inspect worker logs and PostgreSQL/Redis readiness; abandoned jobs remain recoverable from PostgreSQL.
- Production configuration rejection: remove demo seeding, use explicit non-local CORS origins, and ensure active providers are marked `PRODUCTION` with authorized secret references.
- This repository does not include real government integrations, production secret management, distributed rate-limit coordination, TLS termination, WAF policy, or an executed backup restore test.

Shutdown and restart without deleting data:

```text
docker compose stop
docker compose start
```

Do not use `docker compose down -v` unless intentional destruction of the PostgreSQL volume has been approved.
