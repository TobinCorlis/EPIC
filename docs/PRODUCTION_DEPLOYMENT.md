# EPIC production deployment

## Architecture

Run three independently restartable components:

1. **Web API** — FastAPI/Uvicorn behind an HTTPS reverse proxy or managed load balancer.
2. **PostgreSQL** — persistent relational storage.
3. **Research worker** — `python -m app.services.research_worker`. The process is durable, but automated research is not implemented: a claimed job is marked `not_implemented` and is not given a result summary.
4. **Fact-check worker** — `python -m app.services.factcheck_worker`. It runs queued source and claim checks. Set `FACTCHECK_CONTACT_EMAIL`. Optional: `FACTCHECK_LLM_BASE_URL`, `FACTCHECK_LLM_API_KEY`, `FACTCHECK_LLM_MODEL`, `COURTLISTENER_API_TOKEN`, `GOVINFO_API_KEY`, and `FACTCHECK_SAVE_PAGE_NOW`. A network failure is stored as `check_failed` and does not mark the source verified.

## Required production settings

Set `APP_ENV=production`, a PostgreSQL `DATABASE_URL`, a random `SECRET_KEY` of at least 32 characters, explicit `ALLOWED_ORIGINS` and `TRUSTED_HOSTS`, and `AUTO_CREATE_SCHEMA=false`.

Production configuration intentionally fails fast when SQLite, wildcard CORS, the development secret, or automatic schema creation is used.

## Database migrations

Alembic is included as a dependency. Before public deployment, initialize and commit migration scripts, then run migrations as a release step before starting web and worker processes. `Base.metadata.create_all()` is for local development only.

## Health checks

- `/health/live` confirms that the process is running.
- `/health/ready` verifies database connectivity.

## Security baseline

Terminate TLS at the load balancer/reverse proxy, forward proxy headers only from trusted infrastructure, keep secrets in a managed secret store, use a non-superuser database account, restrict inbound database access, rotate secrets, and back up PostgreSQL.

## Local production-shaped run

From the repository root:

```bash
docker compose up --build
```

The site is then available at `http://localhost:8000`; the worker runs separately and claims queued research jobs from PostgreSQL.


## Database migrations

Set `AUTO_CREATE_SCHEMA=false`, then run `alembic upgrade head` as a release step before starting web and worker processes. Back up the database before any migration and test downgrades in staging.

## Authorization

Set `ENFORCE_AUTHORIZATION=true` in production. Write operations require a valid bearer session. Debate-management actions are restricted to the debate owner, moderators, or administrators, while administrator-only account changes are exposed under `/admin`.

Knowledge writes, argument creation, and evidence challenges follow the same flag. After `alembic upgrade head`, create the first administrator from `backend/`:

```bash
python -m app.cli create-admin --email admin@example.com --name "EPIC Admin" --password "replace-this-password"
```

The command creates one administrator and then refuses to create another.
