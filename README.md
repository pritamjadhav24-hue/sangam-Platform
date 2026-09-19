# SANGAM / GovOrchestrator

SANGAM is a local prototype for purpose-bound government service orchestration. It includes JWT authentication, PostgreSQL persistence, workflow orchestration, dependency handling, schema mapping, entity/conflict review, notifications, and audit correlation.

The production-upgrade foundation adds PostgreSQL-backed departments, providers, services, schemes, and scheme requirements. `GET /api/catalog` exposes the configured catalog. Demo users and initial catalog rows are isolated in the development seed modules and are inserted only when the corresponding database tables are empty and seeding is enabled (`SANGAM_SEED_CATALOG=true`).

## Run locally with Docker Compose

Prerequisites:

- Docker Desktop with Compose support

Configure local secrets without committing them:

```text
copy .env.example .env
```

Edit `.env` and replace the placeholder PostgreSQL password, JWT secret, and demo bootstrap passwords. The Compose backend connects to the PostgreSQL service as `postgres`, not to a developer-installed database on `localhost`.

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
