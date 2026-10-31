# Running the Plain English Data Assistant

This manual covers the local development setup. The app starts with SQLite and development authentication, so Gemini and PostgreSQL are optional for the basic demo.

## Requirements

- Python 3.11 or newer
- Git
- Optional: Docker Desktop, for PostgreSQL
- Optional: a Gemini API key, for model-assisted routing, SQL generation, and answer verification

## 1. Install the project

Run these commands in PowerShell from the project directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal and activate again. This changes policy only for the current PowerShell process.

Open `.env` in an editor. For the default SQLite demo, leave `DATABASE_URL=sqlite:///data/demo.db` and `AUTH_MODE=dev`. No database setup is needed. The app creates the demo database, sample sales, and sample reporting documents on startup.

## 2. (Optional) Enable Gemini

Create an API key in [Google AI Studio](https://ai.google.dev/gemini-api/docs/get-started?authuser=3&lang=python) and set it in `.env`:

```dotenv
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-3.8-flash
```

Restart the app after changing `.env`. Without a key, the app can still answer supported catalog questions using deterministic routing and reviewed query templates; it does not generate free-form LLM answers. With a key, Gemini assists with routing and SQL generation, then drafts and checks evidence-backed answers. Provider errors may result in a deterministic fallback.

Google's free tier has model-specific quotas and its data-use terms allow submitted prompts and responses to be used to improve Google products. Use synthetic demo data while testing; do not send confidential data through a free-tier key. See [pricing and data use](https://ai.google.dev/gemini-api/docs/pricing) and [billing tiers](https://ai.google.dev/gemini-api/docs/billing).

## 3. Start the API

```powershell
uvicorn app.main:app --reload
```

The API listens at <http://127.0.0.1:8000>. Open <http://127.0.0.1:8000/docs> for interactive API documentation. Stop the server with `Ctrl+C`.

Check the health endpoint in a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## 4. Ask a question

In the development default, the app uses a fixed viewer identity. You do not need to provide an API key or role header.

```powershell
$body = @{ question = "What is the total sales amount by region?" } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/ask `
  -ContentType "application/json" `
  -Body $body
```

The response contains:

- `answer`: the answer or a readable rendering of the evidence
- `route`: `data`, `documents`, `hybrid`, or `unsupported`
- `evidence`: query results and/or document passages used
- `limitations`: caveats, fallback details, or why an answer was unavailable
- `latency_ms`: time spent handling the question
- `llm_used`: whether Gemini was used
- `model_status`: `disabled`, `available`, `used`, or `degraded`
- `node_timings_ms`: elapsed milliseconds for each workflow node that ran
- `provider_failures`: safe Gemini failure categories without provider response text

Try document questions such as `What does the fiscal year mean?` or data questions such as `What is the total sales amount by region?`.

### Add documents and enable semantic retrieval

Create a directory of `.txt` and `.md` files, then ingest them with a tenant and minimum role. For the default local identity, use `local-dev-tenant`:

```powershell
python -m app.ingestion.documents .\my-documents --tenant-id local-dev-tenant --min-role viewer
```

The app chunks files and indexes them in SQLite. Tenant and role metadata are applied before passages can be returned. Re-run ingestion on the same directory after adding, editing, or deleting files; it synchronizes that directory and removes stale chunks from the local indexes.

To add semantic ranking, set `GEMINI_API_KEY` in `.env` and build document vectors:

```powershell
python -m app.ingestion.index_vectors
```

Search combines Chroma semantic neighbors with BM25 results. Chroma's persistent local index is stored under `data/chroma/`. Without indexed vectors or if semantic search is unavailable, search falls back to BM25. Chroma's persistent local client is intended for development and testing; use a secured server-backed Chroma deployment for a deployed multi-user service.

## Shared rate limits (optional locally)

By default, development uses a process-local sliding-window limiter. To exercise the shared Redis limiter locally, start the optional Redis Compose service:

```powershell
docker compose --profile shared-limits up -d redis
```

Set `RATE_LIMIT_REDIS_URL=redis://localhost:6379/0` in `.env` and restart the API. When this URL is configured, Redis failures return a temporary 503 instead of switching to per-process counters. Production configuration requires this URL; use a managed Redis deployment with authentication, TLS, network restrictions, and monitoring for a real service.

## 5. (Optional) Run with PostgreSQL

Docker Desktop must be running. In `.env`, set distinct local passwords for the database administrator and application role. For example, generate each using:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Set the values and database URLs in `.env` (replace the placeholders with the same passwords you set):

```dotenv
POSTGRES_PASSWORD=your-admin-password
APP_DB_PASSWORD=your-distinct-app-password
DATABASE_URL=postgresql://assistant_app:your-distinct-app-password@localhost:5432/analytics
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:your-admin-password@localhost:5432/analytics
```

Use URL-safe passwords as above so special characters do not need URL escaping. Start PostgreSQL and apply the schema:

```powershell
docker compose up -d postgres
docker compose ps
python -m alembic upgrade head
```

Then start the app as usual:

```powershell
uvicorn app.main:app --reload
```

The migration creates sample sales records, the approved sales view, and tenant-based row-level security. The runtime app role is restricted to read-only access. Keep these local demo credentials out of production. To stop PostgreSQL, run `docker compose down`; to also delete its persisted local database volume, run `docker compose down -v`.

## Authentication modes

`AUTH_MODE=dev` is the local default. It always grants the fixed `local-dev-user` viewer identity; passing `X-Role` does not grant privileges.

For JWT mode, set `AUTH_MODE=jwt` and configure `AUTH_JWT_SECRET` (at least 32 bytes), `AUTH_JWT_ISSUER`, and `AUTH_JWT_AUDIENCE` in `.env`. The identity provider must issue an HS256 token containing `exp`, `iss`, `aud`, `sub`, `tenant_id`, and `role` claims. Allowed roles are `viewer`, `analyst`, and `admin`. Send the token as `Authorization: Bearer <token>`. Production refuses to start in development auth mode. Do not enable JWT mode until those values match a trusted token issuer.

## Run the evaluation and tests

With the virtual environment active:

```powershell
python -m app.evaluation.run
python -m app.evaluation.run --iterations 20
python -m pytest -q
```

The PostgreSQL integration test is skipped unless `TEST_POSTGRES_URL` points to a migrated test database. The rest of the tests use local fixtures and SQLite.
The evaluator disables Gemini calls so runs are repeatable and do not consume API quota. It reports retrieval hit@3, workflow route/evidence success, SQL rejection, tenant and viewer-access checks, and measured p50/p95 workflow latency. The --iterations option sets runs per workflow question.

Groundedness is reported as not_measured because live Gemini answer evaluation requires a representative labeled set and human review.

## Troubleshooting

- **`GEMINI_API_KEY` errors:** confirm `.env` is in the project root and the key is set; restart Uvicorn. Without a key, only deterministic supported paths are available.
- **PostgreSQL connection refused:** confirm Docker Desktop is running and `docker compose ps` reports the database healthy.
- **Alembic cannot connect:** verify both PostgreSQL URLs and their credentials in `.env`; run migrations after the database is healthy.
- **Port already in use:** stop the other process using port 8000 (API) or 5432 (PostgreSQL), or adjust the local port mapping for PostgreSQL.
- **Unexpected configuration after editing `.env`:** stop and restart Uvicorn so settings are reloaded.

## Safety notes

- Never commit `.env`; it contains credentials. Keep using `.env.example` for safe defaults and documentation.
- The demo uses synthetic sample data. Do not connect real sensitive data until authentication, access policies, deployment configuration, and evaluation have been reviewed for that use.
- Without `RATE_LIMIT_REDIS_URL`, the rate limiter is process-local and intended for local development only. Production configuration requires the shared Redis limiter.
