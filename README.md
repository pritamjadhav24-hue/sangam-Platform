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
