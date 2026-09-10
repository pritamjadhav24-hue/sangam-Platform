# SANGAM / GovOrchestrator

SANGAM is a local prototype for purpose-bound government service orchestration. It includes JWT authentication, PostgreSQL persistence, workflow orchestration, dependency handling, schema mapping, entity/conflict review, notifications, and audit correlation.

## Run locally with Docker Compose

Prerequisites:

- Docker Desktop with Compose support

Configure local secrets without committing them:

```text
copy .env.example .env
```

Edit `.env` and replace the placeholder PostgreSQL password, JWT secret, and demo bootstrap passwords. The Compose backend connects to the PostgreSQL service as `postgres`, not to a developer-installed database on `localhost`.

Start the complete local stack:

```text
docker compose up --build
```

Open:

- Frontend: http://localhost:5173
- Backend health: http://localhost:8000/

Stop the stack normally with:

```text
docker compose down
```

PostgreSQL data is stored in the named volume `sangam-postgres-data`, so normal shutdown does not remove applications, workflow history, events, notifications, or audit data. The SANGAM admin Demo Reset clears deterministic application/demo state while retaining the database volume. Removing the volume is a separate destructive operation and is not required for normal resets.

The PostgreSQL container is available only on the Compose network; it is not exposed as a public host port. Backend and frontend retain the existing local ports 8000 and 5173.

## Existing local scripts

Without containers, the existing `run_platform.bat` and `run_platform.sh` scripts continue to start the local backend and Vite development server. The local backend still requires a PostgreSQL `DATABASE_URL` and JWT/bootstrap environment configuration.

## Validation

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
