# SANGAM — Connecting Government Services, Seamlessly

**SANGAM** (internal/backend name **GovOrchestrator**) is a federated interoperability and orchestration layer for government digital services, built for **Smart India Hackathon 2026, Problem Statement 26129 — "System Integration and Interoperability Among Government Digital Platforms"**.

SANGAM does **not** replace existing department systems and never reads their databases. It sits between citizen-facing portals and independent department systems, discovers which system can satisfy each requirement of a service, fetches verified data through reusable adapters (with the citizen's consent), maps it into one canonical representation, validates it and tracks the whole application — with a full audit trail.

> **Synthetic-data disclaimer.** Every department system, provider, citizen and document in this repository is **synthetic sandbox data** built for the prototype. No live Maharashtra/Government of India system is connected, and no real personal data is used.

---

## 1. Architecture

```
Citizen portal (React)          Officer desk            Admin console
        │                            │                        │
        └──────────────┬─────────────┴────────────────────────┘
                       ▼
             SANGAM API  (FastAPI, JWT + role guards)
                       │
     ┌─────────────────┼───────────────────────────────────────────┐
     │  Scheme catalogue → requirement vocabulary → capability     │
     │  Provider registry (PostgreSQL) → health + priority → select│
     │  Consent (per requirement, versioned) → policy check        │
     │  Reusable adapter (REST / SOAP-wrapper / CSV / Dept. API)   │
     └─────────────────┼───────────────────────────────────────────┘
                       ▼  HTTP only
   Revenue :9101  Education :9102  Social Welfare :9103  Health :9104  Transport :9105
   (+ :9106 for Agriculture, Labour, Civil Supplies, Housing, Skills)
      each its own uvicorn service (app.department_api.services.<key>)
                       │
   revenue_db  education_db  welfare_db  health_db  transport_db  (one DB each)
                       │
     response → adapter normalisation → schema mapping (PostgreSQL)
              → canonical record → validation / entity resolution
              → authoritative application state (PostgreSQL)
              → citizen notification + audit ledger + Admin lineage
```

Key rules the implementation enforces:

- **PostgreSQL is authoritative** for applications, requirements, consents, documents, provider jobs, incidents, notifications and the provider/capability registry. Redis is optional and non-authoritative (queue, cache, rate limits).
- **Provider selection is data-driven**: requirement code → enabled capabilities → provider health → priority. No requirement → department mapping is hard-coded in the engine.
- **Department systems stay independent**: SANGAM only reaches them over HTTP through the adapter layer; each department sandbox has its own database.
- **A department outage is not a SANGAM outage**: the platform stays *Healthy*; only the affected department is shown *Unavailable* (Admin → Overview and Providers → *Department systems*), with its incidents, fallback use and affected applications/citizens.
- **Citizens never see internals**: provider, department, adapter, API and fallback details are stripped from every citizen response.

## 2. Key features

**Citizen portal** (English/मराठी)
- Dashboard, scheme catalogue (10 schemes), scheme detail, dynamic application form generated from the scheme's requirements.
- Per-requirement **Auto-Fill** with a per-requirement consent dialog (Accept/Reject); requirements are fulfilled independently and concurrently — one failure never blocks another.
- Per-requirement **manual upload** for document/certificate requirements: upload from the device or take a picture with the camera (JPG/PNG/PDF, up to 5 MB, content-checked), then preview, replace/retake or remove before submission.
- **Deterministic scheme eligibility**: each scheme's written criteria are rules evaluated against verified data — *Eligible*, *Not eligible* (with the failed criteria) or *Eligibility cannot be confirmed yet* when data is missing, unverified, expired or conflicting. No scores.
- Review → submit (readiness enforced server-side; submitted applications are immutable), tracking, notifications, verified document view/download.

**Orchestration engine**
- Dynamic provider discovery, in-request **fallback cascade** to the next eligible provider, retry classification, action-required hand-off to manual upload.
- Provider **incidents** (one per provider outage, not per citizen) with traced impact — affected citizens, applications and schemes, blocked operations, pending retries, successful fallbacks and recovered applications, provider jobs with dead-letter handling and **automatic recovery replay** of eligible dead-letter jobs when a provider recovers (async job mode).
- Canonical schema mapping (PostgreSQL `schema_mappings` for department APIs, deterministic canonical rules for the original providers), validation, entity resolution with officer review for ambiguous matches, local metadata-only mapping suggestions with human review.
- Idempotency keys, optimistic concurrency (`applications.version`), row locking, hash-chained audit ledger.

**Officer desk** — review queue (entity/conflict/mapping reviews), decisions with mandatory remarks, notifications.

**Admin console** — Dashboard, Applications, Application Detail (execution lineage incl. fallback), Providers, Provider Detail, Capability Matrix, Analytics/Reports, Schemes/Requirements, Alerts/Exceptions, Audit Lineage, Profile/Access, controlled provider-outage simulation and Demo Reset.

## 3. Technology stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite, plain CSS, Vitest + Testing Library; served by nginx in containers |
| Backend | Python, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, RapidFuzz |
| Data | PostgreSQL (platform, authoritative); SQLite per department sandbox (or PostgreSQL via `SANDBOX_DB_URL_<DEPT>`) |
| Queue/cache | Redis (optional; required only for async provider jobs) |
| Deployment | Docker Compose (postgres, redis, migrate, department-api, backend, worker, frontend) |

## 4. Repository structure

```
backend/
  main.py                    SANGAM API entry point (startup: migration check, seeding, hydration)
  alembic/                   PostgreSQL migrations (head: 0016_provider_incidents)
  app/api/                   auth, citizen, officer, admin, notification, catalog routes
  app/core/                  persistence (models, seeds, reset), auth, audit bus, admin insights, Redis, jobs
  app/engine/                registry, adapters, requirement fulfillment, retry policy, consent,
                             schema/semantic mapping, validation, entity resolution, workflow
  app/department_api/        independent department REST APIs (separate service)
  app/sandbox/               per-department sandbox models + deterministic synthetic seeds
  app/mocks/                 original in-process demo providers (Revenue, Education, Social Welfare, DBT, Identity)
  app/seeds/                 demo accounts + synthetic citizen identity pool
  app/worker.py              async provider-job worker
  tests/                     unittest suite (runs against a PostgreSQL database)
frontend/
  src/api.js                 single API client (all backend contracts)
  src/pages/, src/pages/admin/, src/components/
  nginx.conf, Dockerfile     production image (proxies /api to the backend)
docker-compose.yml, .env.example
```

## 5. Configuration (environment variables)

Two example files exist:

- **`.env.example`** (repository root) — Docker Compose.
- **`backend/.env.example`** — running the backend directly on a host. The backend loads `backend/.env` automatically; real environment variables always win.

| Variable | Purpose |
|---|---|
| `SANGAM_ENV` | `development` (demo profile) or `production` (refuses demo seeding, sandbox providers, local CORS, weak `JWT_SECRET`; hides `/docs`; disables Demo Reset) |
| `DATABASE_URL` | PostgreSQL URL (`postgresql+psycopg://…`); Compose builds it from `POSTGRES_*` |
| `JWT_SECRET`, `JWT_EXPIRES_SECONDS` | Token signing secret (≥32 random chars) and lifetime |
| `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_CREDENTIALS` | Cross-origin callers (the Vite dev server). The Compose frontend is same-origin |
| `VITE_API_BASE_URL` | Frontend build-time API URL. Empty → production build calls same-origin `/api` |
| `SANGAM_SEED_CATALOG`, `SANGAM_SEED_DEMO_USERS`, `SANGAM_SEED_SYNTHETIC_DATA`, `SANGAM_SEED_DEPARTMENT_PROVIDERS` | Idempotent demo seeding (schemes/vocabulary/in-process providers, accounts, synthetic citizens, department sandbox providers) |
| `SANGAM_*_PASSWORD`, `SANGAM_DEMO_CITIZEN_PASSWORD` | Bootstrap passwords for demo accounts (hashed with scrypt on first start) |
| `SANGAM_ALLOW_DEMO_CITIZEN_SWITCH` | Enables the backend demo citizen switch endpoints (never in production; the web app no longer uses them) |
| `DEPARTMENT_API_BASE_URL` | Base URL of the combined department API (legacy single-service mode) |
| `DEPARTMENT_API_URL_<KEY>` | Per-department service URL (`REVENUE`, `EDUCATION`, `SOCIAL_WELFARE`, `MUNICIPAL_HEALTH`, `TRANSPORT`, …). Read by SANGAM from `backend/.env.integrations` (see `.env.integrations.example`); when set, the department is probed and monitored as its own system |
| `SANDBOX_DB_URL_<KEY>` | A department's own database (default: SQLite under `backend/data/sandboxes`). Read only by the department services, from `backend/.env.departments` |
| `SANGAM_FEDERATED_DEPARTMENTS` | Retires the in-process department mocks so every department requirement goes through the department services (Revenue income primary, Social Welfare verified household income as fallback) |
| `SANGAM_PUBLIC_DEMO` | Enables the demo-account selector on the sign-in page and server-side sign-in for the seven synthetic `DEMO-CIT-00x` accounts only. Refused in production |
| `DEPARTMENT_SANDBOX_AUTO_SEED` | Department API creates + seeds its sandbox databases on first start |
| `DEPARTMENT_API_KEY_TRANSPORT`, `PROVIDER_TRANSPORT_SANDBOX_*_API_KEY` | API key for the Transport sandbox providers (API-key auth demo). Must be set, otherwise those providers report `MISCONFIGURED` and are never selected |
| `REDIS_ENABLED`, `REDIS_URL`, `ASYNC_PROVIDER_JOBS` | Redis + async provider jobs (worker). Off on a plain host setup |
| `RATE_LIMIT_*` | Login / application / consent / replay rate limits |

Never commit a real `.env`; both are git-ignored.

## 6. Local setup (without Docker)

Prerequisites: Python 3.9+ (3.12 in containers), Node.js 20+, PostgreSQL 14+.

```bash
# 1. Database
createdb sangam_db
cp backend/.env.example backend/.env        # then edit DATABASE_URL, JWT_SECRET and the passwords

# 2. Backend dependencies + migrations
cd backend
pip install -r requirements.txt
alembic upgrade head

# 3. Department systems — optional PostgreSQL databases (writes backend/.env.departments; never drops)
python -m app.sandbox.provision_postgres
cp .env.integrations.example .env.integrations
#    then one terminal per department (each seeds its own database on start)
python -m uvicorn app.department_api.services.revenue:app        --port 9101
python -m uvicorn app.department_api.services.education:app      --port 9102
python -m uvicorn app.department_api.services.social_welfare:app --port 9103
python -m uvicorn app.department_api.services.health:app         --port 9104
python -m uvicorn app.department_api.services.transport:app      --port 9105
python -m uvicorn app.department_api.services.other:app          --port 9106
#    (the original single service, app.department_api.main:app, still works for a quick start)

# 4. SANGAM backend (new terminal, from backend/) — seeds demo data on first start
python -m uvicorn main:app --port 8001

# 5. Frontend (new terminal)
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173. `run_platform.bat` / `run_platform.sh` perform steps 2–5 in one go. Department sandboxes can also be managed by hand: `python -m app.sandbox.manage create-all | seed-all | reset-all | status`.

### Running every service (Windows PowerShell)

Each process runs in its own PowerShell window from the repository root (the folder that contains `backend` and `frontend`); `--app-dir backend` tells uvicorn where the code is. Configuration files are found relative to the code, so the working directory does not change which database is used. **Do not add `--reload`** for these databases: a reloading server re-runs its idempotent startup seeding on every code edit.

| Process | Port | Command | Database | Configuration read |
|---|---|---|---|---|
| SANGAM backend | 8001 | `python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8001` | `sangam_db` (`DATABASE_URL`) | `backend/.env`, `backend/.env.integrations` |
| Revenue API | 9101 | `python -m uvicorn app.department_api.services.revenue:app --app-dir backend --host 127.0.0.1 --port 9101` | `revenue_db` | `backend/.env.departments` (`SANDBOX_DB_URL_REVENUE`) |
| Education API | 9102 | `python -m uvicorn app.department_api.services.education:app --app-dir backend --host 127.0.0.1 --port 9102` | `education_db` | `SANDBOX_DB_URL_EDUCATION` |
| Social Welfare API | 9103 | `python -m uvicorn app.department_api.services.social_welfare:app --app-dir backend --host 127.0.0.1 --port 9103` | `welfare_db` | `SANDBOX_DB_URL_SOCIAL_WELFARE` |
| Health API | 9104 | `python -m uvicorn app.department_api.services.health:app --app-dir backend --host 127.0.0.1 --port 9104` | `health_db` | `SANDBOX_DB_URL_MUNICIPAL_HEALTH` |
| Transport API | 9105 | `python -m uvicorn app.department_api.services.transport:app --app-dir backend --host 127.0.0.1 --port 9105` | `transport_db` | `SANDBOX_DB_URL_TRANSPORT`, `DEPARTMENT_API_KEY_TRANSPORT` |
| Other departments | 9106 | `python -m uvicorn app.department_api.services.other:app --app-dir backend --host 127.0.0.1 --port 9106` | `agriculture_db`, `labour_db`, `civil_supplies_db`, `housing_db`, `skills_db` | `SANDBOX_DB_URL_<KEY>` for each |
| Frontend | 5173 | `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` | — | `VITE_API_BASE_URL` (unset = `http://127.0.0.1:8001/api` in dev) |

SANGAM reaches each department only at `DEPARTMENT_API_URL_<KEY>` from `backend/.env.integrations` (never its database). Start the department APIs first, then SANGAM, then the frontend.

**What starting does to data.** A department service creates missing tables/columns and inserts its seed rows only when they are missing (`DEPARTMENT_SANDBOX_AUTO_SEED=true`); SANGAM inserts missing catalog/provider/demo rows (`SANGAM_SEED_*=true`). Both are insert-only and idempotent: on already-seeded databases they change nothing. For a start that writes nothing at all, set the flags in that window first — a real environment variable always wins over the file:

```powershell
$env:DEPARTMENT_SANDBOX_AUTO_SEED = "false"   # before starting a department API
$env:SANGAM_SEED_CATALOG = "false"; $env:SANGAM_SEED_DEMO_USERS = "false"; $env:SANGAM_SEED_SYNTHETIC_DATA = "false"; $env:SANGAM_SEED_DEPARTMENT_PROVIDERS = "false"   # before SANGAM
```

**Health checks** (a department's `/health` also checks its own database and answers 503 when it cannot reach it):

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health/live
Invoke-RestMethod http://127.0.0.1:8001/health/ready
9101..9106 | ForEach-Object { try { $r = Invoke-RestMethod "http://127.0.0.1:$_/health"; "$_ $($r.status) db=$($r.database)" } catch { "$_ DOWN" } }
```

A department that is down appears as *Unavailable* in Admin → Overview / Providers while *SANGAM platform* stays *Healthy*.

**Stopping / restarting one department.** Press `Ctrl+C` in its window, or stop whatever listens on its port, then run its command again:

```powershell
Get-NetTCPConnection -LocalPort 9101 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess }   # stop Revenue only
python -m uvicorn app.department_api.services.revenue:app --app-dir backend --host 127.0.0.1 --port 9101   # start it again
```

### Migrations

```bash
cd backend
alembic upgrade head      # apply
alembic current           # show revision
```

The backend refuses to start unless the database is exactly at the expected head revision.

### Seed / demo data

With the seed flags enabled, the backend seeds on every start (each step only inserts what is missing):

- 10 schemes and their 24 scheme requirements; 21-code requirement vocabulary.
- 5 original in-process providers (Revenue, Social Welfare, Education, Authorized DBT, State Resident Registry) and 16 department sandbox providers across 10 departments, with capabilities and schema mappings.
- 60 synthetic citizens; demo accounts (below).

The department API seeds each department database deterministically (fixed RNG), so the same citizen always has the same records.

### Resetting the demo

Admin → Dashboard → **Reset Demo** clears all runtime activity — applications, documents, consents, notifications, provider jobs, incidents, events and the audit ledger — while keeping accounts, citizens, schemes, vocabulary, providers, capabilities and mappings. It is refused in production mode.

## 7. Production / container deployment

```bash
cp .env.example .env      # replace every "replace-…" value
docker compose up -d --build
docker compose ps
```

Start order is enforced by health checks: PostgreSQL + Redis → `migrate` (runs `alembic upgrade head` once) → department API (auto-seeds sandboxes) → backend + worker → frontend.

- Frontend: `http://<host>:${FRONTEND_PORT:-5173}` (nginx serves the SPA and proxies `/api` and `/health` to the backend, so no CORS is needed).
- Backend (diagnostics): `http://<host>:${BACKEND_PORT:-8001}`.
- PostgreSQL and Redis are only on the internal network. Data persists in the `sangam-postgres-data` and `sangam-sandbox-data` volumes.
- Put TLS termination (a reverse proxy or load balancer) in front of the frontend port for any public deployment; the containers speak plain HTTP.

The repository targets no specific cloud. Any host that runs Docker Compose works; for a managed platform, run the same images with the same environment variables.

`SANGAM_ENV=production` is intended only for a deployment with real, authorized `PRODUCTION` providers — it deliberately refuses to start with the sandbox providers, demo seeding or demo accounts. A hosted **demo** therefore runs with `SANGAM_ENV=development` and strong secrets.

### Health checks

| Endpoint | Meaning |
|---|---|
| `GET /health/live` | Backend process is alive |
| `GET /health/ready` | PostgreSQL reachable and at migration head; Redis and a fresh worker heartbeat when Redis is enabled |
| `GET /` (department API) `GET /health` | Department API alive |

Health responses contain status only — no configuration values or secrets.

### Backup

PostgreSQL is the only state that must be backed up (`pg_dump --format=custom`). Redis is rebuildable; department sandboxes are reproducible from their deterministic seeds.

## 8. Demo accounts and roles

| Account | Role | Notes |
|---|---|---|
| `CITIZEN_001` (Rahul Kumar) | Citizen | Original demo citizen |
| `CITIZEN_002` | Citizen | |
| `SYN-CIT-00001` … (10 personas) | Citizen | Sign in with the shared `SANGAM_DEMO_CITIZEN_PASSWORD` |
| `OFFICER_MH_01` | Officer | Review queue |
| `ADMIN_MH_01` | Admin | Admin console |
| `DEMO-CIT-001` … `DEMO-CIT-007` | Citizen | Public demo accounts (`SANGAM_PUBLIC_DEMO=true`): chosen from the sign-in page selector, no password shown. Scenarios: eligible (Rahul Kumar), missing information, several documents, fallback provider (Amit Shinde), affected by a Revenue outage (Neha Pawar), unconfirmed identity (Sachin More), not eligible (Kiran Kale) |

Passwords are whatever you set in `.env` (`SANGAM_*_PASSWORD`, `SANGAM_DEMO_CITIZEN_PASSWORD`); the UI never displays or pre-fills them. Sessions are JWTs kept in memory only, so a browser refresh requires signing in again (Admin returns to the page it was on, per tab).

## 9. Main demo scenario (citizen)

1. Sign in as a citizen → Dashboard → **Schemes** → *Post-Matric Higher Education Scholarship* → **Apply**.
2. The form lists the scheme's requirements. For each one, click **Auto-Fill** → accept the consent dialog. Requirements resolve independently (in parallel if clicked together).
3. Use **Upload manually** for any document the citizen prefers to provide themselves.
4. **Review** → **Submit** (only enabled once every mandatory requirement is satisfied) → Tracking and Notifications update.
5. Officer: sign in as `OFFICER_MH_01` to see the review queue. Admin: open the application in **Applications** to see the full lineage.

## 10. Failure / fallback scenario

### Federated departments (`SANGAM_FEDERATED_DEPARTMENTS=true`)

| Priority | Provider | Department service |
|---|---|---|
| 10 · **Authoritative source** | Revenue Sandbox API – Income Certificates | Revenue :9101 → `revenue_db` |
| 30 · **Authorized fallback** | Social Welfare Department API – Verified Household Income | Social Welfare :9103 → `welfare_db` |

Priority, capability and authorization are separate. A provider is selected only if the registry *authorizes* it for the requirement — as the authoritative source, or as an explicitly authorized fallback; priority only orders providers within the same role. A department that merely *can* answer (a capability without authorization) is never used, even when the authoritative source is down. Authorization is read from the capability row (`payload.authorization`), else from the registered provider definition; anything undeclared is not selected. "No record" from one department moves on to the next authorized provider; only when every authorized provider has answered is it reported as *no record* — if one could not be asked, the citizen sees *temporarily unavailable* instead.

1. Stop the Revenue service (or Admin → Providers → *Department systems* → Revenue → **Simulate outage**).
2. Sign in as **Amit Shinde (DEMO-CIT-004)** and Auto-Fill: income is verified from Social Welfare; domicile (Revenue only) waits with a generic "temporarily unavailable" notice; Education records are unaffected.
3. Admin sees *SANGAM platform: Healthy*, *Revenue Department: Unavailable*, the open incidents and the affected applications, and **Activity** shows the exchange step by step: requesting department → SANGAM → registry → Revenue skipped → fallback policy → Social Welfare API → entity resolution → normalization → verification → result. Admin notifications link to the incident, provider or application. Restart Revenue (or **Restore department**) and the incidents resolve.

### Legacy in-process providers

`INCOME_PROOF` has two registered providers for the same capability:

| Priority | Provider | Path |
|---|---|---|
| 10 (primary) | Revenue Department | in-process demo provider |
| 20 (alternate) | Revenue Sandbox API – Income Certificates | HTTP → department API → Revenue sandbox database |

1. Admin → **Providers** → simulate **Revenue Department** unavailable. An incident opens (Alerts).
2. Sign in as a synthetic citizen that holds an issued income certificate in the Revenue sandbox (e.g. **SYN-CIT-00002 Neha Kale**, SYN-CIT-00003, -00004, -00005, -00012 or -00028) and Auto-Fill **Income proof**.
3. Discovery skips the unavailable primary, selects the alternate, retrieves over HTTP and maps `annual_income → incomeAmount`. The citizen simply sees *Verified*.
4. Admin → Application Detail shows the lineage: *Revenue Department (PRIMARY) — skipped: unavailable → Revenue Sandbox API (FALLBACK) → retrieval succeeded*.
5. *Maharashtra domicile* has no alternate provider: during the outage it stays *retrieval in progress* (retryable), and after repeated failures becomes *action required* with manual upload offered.
6. Restore the provider in Admin → Providers: the incident resolves, eligible dead-letter provider jobs are replayed automatically (async job mode), and the next Auto-Fill uses the primary again. A requirement already satisfied by the fallback or by a manual upload is never overwritten.

## 11. Security notes

- Passwords hashed with scrypt; HS256 JWTs with expiry and unique `jti`; tokens are not persisted server-side or in browser storage.
- Role guards on every route: Admin APIs are Admin-only, Officer APIs Officer-only (mapping reviews Officer/Admin); anonymous → 401, wrong role → 403. Citizens can only read and mutate their own applications (others return 404).
- Input validation with Pydantic (ID patterns, length limits). Manual uploads accept only `text/plain` / `application/json` content up to 200 KB; download filenames are sanitised; nothing is written to the filesystem from uploads.
- Unhandled errors return a generic message (no stack traces); security headers on every API and frontend response; CORS allow-list (wildcard + credentials rejected).
- ORM/parameterised queries only. Provider secrets are referenced by environment-variable name, never stored or returned.
- Rate limits on login, application creation, consent and replay (in-process; not shared across replicas).

## 12. Known limitations

- All department systems and providers are synthetic sandboxes; no real government API is integrated.
- Manual upload stores a text/JSON representation of a document, not binary files.
- Rate limiting is per process; the in-memory legacy compatibility state (snapshotted to PostgreSQL after each request) assumes a single backend replica.
- Automatic dead-letter replay applies to async provider jobs (`ASYNC_PROVIDER_JOBS=true` with Redis). The synchronous per-requirement Auto-Fill path cascades providers within the request and, if all fail, leaves the requirement retryable / action-required rather than creating a queued job.
- Only one requirement (`INCOME_PROOF`) has a configured alternate provider; others have a single provider.
- Analytics trends are limited by the amount of demo activity; fulfilment is dated by the application's last update.
- Roles are fixed (Citizen / Officer / Admin); there is no fine-grained permission editor.
- TLS termination, secret management and backups must be provided by the hosting environment.

## 13. Tests

```bash
cd backend && python -m unittest discover -s tests      # needs a migrated PostgreSQL database
cd frontend && npm test && npm run build
```

Tests clean up the rows they create and never remove the seeded demo vocabulary, providers, citizens or the demo personas' applications. Prefer a dedicated test database (set `DATABASE_URL` for the test run); if you run the suite against the database a live backend is using, restart that backend and use **Reset Demo** afterwards so its in-memory audit ledger re-syncs with PostgreSQL.
