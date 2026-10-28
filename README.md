# Guarded Multi-Agent Analytics

A GenAI analytics API prototype where users ask business questions in plain English and a LangGraph workflow routes them to sample **SQL data** or **reporting documents**. Gemini can assist with routing and answers when configured.

Most NL-to-SQL and RAG demos ignore security. This project treats **authorization, safety, and evaluation** as first-class features instead of afterthoughts.

> **Project status:** This is a local development prototype with some production-inspired controls. It is not ready to deploy with real users or sensitive data. See [the running manual](manual.md) for setup and usage.

## What this build demonstrates

This repository packages a question-answering workflow as a small API service. It demonstrates Gemini-assisted routing and answer generation, validated read-only SQL over sample sales data, document evidence, local development authentication, and an optional PostgreSQL setup with tenant policies. SQLite and deterministic fallbacks make the demo usable without a Gemini key or a database server.

| Local demonstration build (this repository today) | Production-grade service (additional work required) |
|---|---|
| One developer runs the API locally with synthetic sample data. | A deployed service supports multiple users, environments, and operational ownership. |
| Development mode uses one fixed viewer identity. | Identity provider integration, credential rotation, and authorization policies are deployed and reviewed. |
| SQLite is the default; PostgreSQL protections have a local setup path. | Database isolation, migrations, backups, restore, monitoring, and failure recovery are verified in the target environment. |
| Initial tests cover the implemented safety and query paths. | A representative, labeled evaluation suite measures answer quality, retrieval, security, cost, and latency over releases. |
| Logs and a health endpoint support local inspection. | Centralized metrics, tracing, alerting, incident response, and capacity planning are operated. |
| Document search uses the current small demo collection. | Ingestion, indexing, access filtering, refresh, and retrieval quality are built for the actual corpus and scale. |

The production column is a target, not a claim about current capabilities. Do not connect sensitive or production data until the required controls have been implemented, configured, and validated for that deployment. A notebook can be a better choice for one-off analysis; this API structure matters when the workflow needs to be called repeatedly by a UI or service and needs consistent request handling, authorization, evidence, and evaluation.

## What it aims to do

- Turn natural-language questions into **validated, read-only SQL**
- Retrieve document passages with **permission filters applied before ranking**
- Derive user role and tenant from **verified identity claims**, never from client-supplied headers
- Enforce data access in the database itself with **PostgreSQL row-level security**
- Fail visibly with explicit errors, timeouts and degraded-service responses
- Gate every release behind an **evaluation suite** (retrieval, SQL correctness, authorization, latency, cost)

## Architecture

```
Client -> FastAPI -> Auth (verified JWT claims)
                        |
                   Agent graph (LangGraph)
                  /          |           \
          Router        SQL agent      RAG agent
                           |               |
                   SQL validator      Permission filter
                           |               |
                 PostgreSQL (RLS)   BM25 + vector search
```

<Replace with a real diagram once Stage 3 is done.>

## Tech stack

Python, FastAPI, LangGraph, Gemini API, SQLite (demo) / PostgreSQL, SQLGlot, Alembic, pytest, Docker


## Quick start

```bash
git clone https://github.com/<your-username>/secure-multi-agent-analytics.git
cd secure-multi-agent-analytics

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
cp .env.example .env          # then edit .env (see below)

uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

For step-by-step local setup, API examples, optional Gemini and PostgreSQL configuration, and troubleshooting, see [manual.md](manual.md).

## Configuration

All settings live in `.env` (never commit this file). Every variable is documented in `.env.example`.

| Variable | Purpose | Where to get it | Required |
|---|---|---|---|
| `GEMINI_API_KEY` | Gemini model access | Google AI Studio API keys | Optional; required for LLM responses |
| `GEMINI_MODEL` | Gemini model name | Gemini API model catalog | Has default: `gemini-3.8-flash` |
| `ENVIRONMENT` | `development`, `staging` or `production` | You choose | Has default |
| `AUTH_MODE` | `dev` fixed identity or `jwt` verification | You choose; production requires `jwt` | Has default: `dev` |
| `AUTH_JWT_SECRET` | HS256 verification secret (32+ bytes) | Your identity provider/shared-secret provisioning | Required with `AUTH_MODE=jwt` |
| `AUTH_JWT_ISSUER` | Expected JWT issuer | Identity provider configuration | Required with `AUTH_MODE=jwt` |
| `AUTH_JWT_AUDIENCE` | Expected JWT audience | Identity provider/API registration | Required with `AUTH_MODE=jwt` |
| `DATABASE_URL` | SQL backend connection | Leave the default for SQLite; use PostgreSQL connection details for PG | Has default: SQLite demo |
| `MIGRATION_DATABASE_URL` | PostgreSQL owner connection for Alembic | PostgreSQL admin/migration account | Required to run PG migrations |
| `DATABASE_STATEMENT_TIMEOUT_MS` | PostgreSQL statement timeout | Tune for the workload | Has default: `5000` |
| `VIEWER_MIN_GROUP_SIZE` | Minimum rows per viewer aggregate group | Set based on data disclosure policy | Has default: `3` |
| `POSTGRES_PASSWORD` | Local PostgreSQL administrator password for Compose | Generate locally; do not commit | Required only for Compose |
| `APP_DB_PASSWORD` | Local read-only app role password for Compose | Generate locally; do not commit | Required only for Compose |

<Add rows as each stage introduces new variables.>

## Security notes

- API keys stay server-side; rotate them regularly
- `.env` is git-ignored
- Dev-only auth mode is refused in production
- Generated SQL is validated by a parser and schema allowlist, then executed under a read-only database role
- PostgreSQL access uses an approved view and a tenant-scoped row-level security policy; SQLite adds the tenant predicate in application code

## Testing

```bash
pytest
```

## PostgreSQL local testing

SQLite remains the default so `uvicorn app.main:app` still runs without a database service. To exercise the PostgreSQL backend, put distinct `POSTGRES_PASSWORD` and `APP_DB_PASSWORD` values in `.env`, then set:

```dotenv
DATABASE_URL=postgresql://assistant_app:<APP_DB_PASSWORD>@localhost:5432/analytics
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<POSTGRES_PASSWORD>@localhost:5432/analytics
```

Use URL-safe generated passwords (for example, `python -c "import secrets; print(secrets.token_urlsafe(32))"`) so reserved characters do not need escaping.

```powershell
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app
```

The Compose init script creates a non-superuser login role for the app and a separate non-login role that owns the read view. The migration creates the tenant-keyed table, enables and forces RLS, installs a default-deny tenant/role policy, creates the approved `sales` view, and adds synthetic demo records. The app connection is read-only and receives tenant/role session settings for each request. Do not use the local demo credentials outside a developer machine.

The PostgreSQL cross-tenant integration test runs when `TEST_POSTGRES_URL` points to the migrated `assistant_app` database URL; otherwise that one integration case is skipped. SQLite tenant isolation, aggregate suppression, query limits, and malicious SQL rejection run offline.

## Setup checklist

| Variable | What it is | Where to get it | Required or optional | Default |
|---|---|---|---|---|
| `ENVIRONMENT` | `development`, `staging`, or `production` | Choose for the deployment | Optional | `development` |
| `AUTH_MODE` | Fixed local identity or verified JWT | Choose; production must use JWT | Optional | `dev` |
| `AUTH_JWT_SECRET` | HS256 secret, at least 32 bytes | Provision from your identity provider/shared-secret store | Required for `AUTH_MODE=jwt` | Unset |
| `AUTH_JWT_ISSUER` | Expected JWT issuer | Identity provider configuration | Required for `AUTH_MODE=jwt` | Unset |
| `AUTH_JWT_AUDIENCE` | Expected API audience | Identity provider/API registration | Required for `AUTH_MODE=jwt` | Unset |
| `GEMINI_API_KEY` | Gemini model credential | Create in Google AI Studio | Optional; required for model answers | Unset |
| `GEMINI_MODEL` | Gemini model ID | Gemini API model catalog | Optional | `gemini-3.8-flash` |
| `LLM_MAX_OUTPUT_TOKENS` | Maximum generated tokens per model call | Tune with evaluation | Optional | `700` |
| `DATABASE_URL` | Runtime structured-data database | SQLite default, or PostgreSQL DSN | Optional | `sqlite:///data/demo.db` |
| `MIGRATION_DATABASE_URL` | PostgreSQL owner/admin DSN for Alembic | PostgreSQL administrator | Required to apply PostgreSQL migrations | Unset |
| `DATABASE_STATEMENT_TIMEOUT_MS` | PostgreSQL query timeout | Tune to workload | Optional | `5000` |
| `VIEWER_MIN_GROUP_SIZE` | Minimum records in a viewer aggregate cell | Set from disclosure policy | Optional | `3` |
| `POSTGRES_PASSWORD` | Local Compose superuser password | Generate locally; keep in `.env` | Required only for PostgreSQL Compose | Unset |
| `APP_DB_PASSWORD` | Local restricted application-role password | Generate locally; keep distinct from admin password | Required only for PostgreSQL Compose | Unset |
| `DEV_RATE_LIMIT_PER_MINUTE` | Development per-user rate limit | Tune for local use | Optional | `120` |
| `STAGING_RATE_LIMIT_PER_MINUTE` | Staging per-user rate limit | Tune for staging | Optional | `60` |
| `PRODUCTION_RATE_LIMIT_PER_MINUTE` | Production per-user rate limit | Tune for capacity/abuse policy | Optional | `30` |
| `DEV_MAX_QUESTION_TOKENS` | Development question token limit | Tune for local use | Optional | `4096` |
| `STAGING_MAX_QUESTION_TOKENS` | Staging question token limit | Tune for model/context | Optional | `2048` |
| `PRODUCTION_MAX_QUESTION_TOKENS` | Production question token limit | Tune for model/context | Optional | `2048` |

Gemini's free tier is suitable for development experiments, subject to current model quotas. Google marks free-tier prompts/responses as eligible for product improvement; avoid sending confidential or production data through a free-tier key. See the [Gemini API pricing and data-use details](https://ai.google.dev/gemini-api/docs/pricing) and [billing tiers](https://ai.google.dev/gemini-api/docs/billing).

## Project status

Actively under development. See the roadmap above.



## Author

Vedika Girap · vedikagirap5@gmail.com
