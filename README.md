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

![Guarded Multi-Agent Analytics Architecture](docs/Guarded%20Multi%20Agents%20Data%20Analytics%20Architecture.png)

## Tech stack

Python, FastAPI, LangGraph, Gemini API, SQLite (demo) / PostgreSQL, SQLGlot, Alembic, ChromaDB, pytest, Docker


## Quick start

Requires Python 3.11 or newer.

```powershell
git clone https://github.com/vedika-girap/Guarded-Multi-Agents-Data-Analytics.git
cd Guarded-Multi-Agents-Data-Analytics

python -m venv .venv
.venv\Scripts\activate        # Windows
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Continue with:

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env

uvicorn app.main:app --reload
```

macOS/Linux: `cp .env.example .env`

API docs: http://localhost:8000/docs

For step-by-step local setup, API examples, optional Gemini and PostgreSQL configuration, and troubleshooting, see [manual.md](manual.md).

## What you get by default vs. what you can enable

| Feature | Default | How to enable | Details |
|---|---|
| Gemini routing/answers | Off; deterministic routing and evidence-shaped answers | Set `GEMINI_API_KEY` in `.env` and restart | [Gemini setup](manual.md#2-optional-enable-gemini) |
| Semantic search (Chroma) | Off; BM25 retrieval | Set `GEMINI_API_KEY`, then run `python -m app.ingestion.index_vectors` | [Document retrieval](manual.md#add-documents-and-enable-semantic-retrieval) |
| JWT auth and roles | Off; fixed viewer identity in dev mode | Set `AUTH_MODE=jwt` and configure issuer, audience, and secret | [Authentication modes](manual.md#authentication-modes) |
| PostgreSQL with row-level security | Off; SQLite | Configure PostgreSQL URLs/passwords, start Compose PostgreSQL, run migrations | [PostgreSQL setup](manual.md#5-optional-run-with-postgresql) |
| Shared Redis rate limiting | Off; process-local limiter | Start Redis and set `RATE_LIMIT_REDIS_URL` | [Shared rate limits](manual.md#shared-rate-limits-optional-locally) |

## Try it

With the API running in development mode, submit a supported question:

```powershell
$body = @{ question = "What is the total sales amount by region?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask -ContentType "application/json" -Body $body
```

The response includes `route` (selected source path), `evidence` (query rows or document passages), `limitations` (caveats and fallback details), `llm_used` (whether Gemini contributed), `model_status` (disabled, available, used, or degraded), and `provider_failures` (safe provider failure categories). `llm_used: false` is expected when no Gemini key is configured.

Example response with Gemini disabled (timings vary):

```json
{
  "answer": "Query results: [{\"region\": \"North\", \"total_sales\": 3200.0}, {\"region\": \"South\", \"total_sales\": 3050.0}, {\"region\": \"West\", \"total_sales\": 3400.0}]",
  "route": "data",
  "evidence": [
    {
      "type": "query",
      "query": "SELECT region, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY region ORDER BY region",
      "rows": [
        { "region": "North", "total_sales": 3200.0 },
        { "region": "South", "total_sales": 3050.0 },
        { "region": "West", "total_sales": 3400.0 }
      ]
    }
  ],
  "limitations": [],
  "llm_used": false,
  "model_status": "disabled",
  "node_timings_ms": {
    "discover": 0.2,
    "generate_sql": 0.1,
    "run_sql": 1.0,
    "answer": 0.1
  },
  "provider_failures": [],
  "latency_ms": 2.0
}
```

With Gemini configured and the API restarted, a successful model-assisted answer has the same evidence but a model-written answer. The exact wording, generated SQL, and timings can vary:

```json
{
  "answer": "Total sales were $3,200 in North, $3,050 in South, and $3,400 in West.",
  "route": "data",
  "evidence": [
    {
      "type": "query",
      "query": "SELECT region, ROUND(SUM(amount), 2) AS total_sales FROM sales GROUP BY region ORDER BY region",
      "rows": [
        { "region": "North", "total_sales": 3200.0 },
        { "region": "South", "total_sales": 3050.0 },
        { "region": "West", "total_sales": 3400.0 }
      ]
    }
  ],
  "limitations": [],
  "llm_used": true,
  "model_status": "used",
  "node_timings_ms": {
    "discover": 1.2,
    "generate_sql": 420.0,
    "run_sql": 4.0,
    "answer": 980.0
  },
  "provider_failures": [],
  "latency_ms": 1410.0
}
```

If `llm_used` is still `false`, check that `GEMINI_API_KEY` is set in the project-root `.env` and restart the API process.

## Demo the guarded behavior

Follow [Demo the guarded behavior](manual.md#demo-the-guarded-behavior) to compare viewer and analyst access and observe an unsafe SQL rejection.

## Configuration

All settings live in `.env` (never commit this file). Every variable is documented in `.env.example`.

| Variable | Purpose | Where to get it | Required / optional | Default |
|---|---|---|---|---|
| `GEMINI_API_KEY` | Gemini model access | Google AI Studio API keys | Optional; needed for model calls | Unset |
| `GEMINI_MODEL` | Gemini model name | Gemini API model catalog | Optional | `gemini-3.8-flash` |
| `GEMINI_EMBEDDING_MODEL` | Embedding model for semantic document search | Gemini API model catalog | Optional | `gemini-embedding-001` |
| `ENVIRONMENT` | `development`, `staging` or `production` | You choose | Optional | `development` |
| `AUTH_MODE` | `dev` fixed identity or `jwt` verification | You choose; production requires `jwt` | Optional | `dev` |
| `AUTH_JWT_SECRET` | HS256 verification secret (32+ bytes) | Your identity provider/shared-secret provisioning | Required with `AUTH_MODE=jwt` | Unset |
| `AUTH_JWT_ISSUER` | Expected JWT issuer | Identity provider configuration | Required with `AUTH_MODE=jwt` | Unset |
| `AUTH_JWT_AUDIENCE` | Expected JWT audience | Identity provider/API registration | Required with `AUTH_MODE=jwt` | Unset |
| `DATABASE_URL` | SQL backend connection | Leave default for SQLite; use PostgreSQL connection details for PG | Optional | `sqlite:///data/demo.db` |
| `MIGRATION_DATABASE_URL` | PostgreSQL owner connection for Alembic | PostgreSQL admin/migration account | Required to run PG migrations | Unset |
| `DATABASE_STATEMENT_TIMEOUT_MS` | PostgreSQL statement timeout | Tune for the workload | Optional | `5000` |
| `VIEWER_MIN_GROUP_SIZE` | Minimum rows per viewer aggregate group | Set based on data disclosure policy | Optional | `3` |
| `POSTGRES_PASSWORD` | Local PostgreSQL administrator password for Compose | Generate locally; do not commit | Required only for Compose | Unset |
| `APP_DB_PASSWORD` | Local read-only app role password for Compose | Generate locally; do not commit | Required only for Compose | Unset |
| `RATE_LIMIT_REDIS_URL` | Shared rate-limit store | Redis connection URL; required in production | Optional locally | Unset |
| `LLM_MAX_OUTPUT_TOKENS` | Maximum generated tokens per model call | Tune with evaluation | Optional | `700` |
| `DEV_RATE_LIMIT_PER_MINUTE` | Development request limit per user | Tune for local use | Optional | `120` |
| `STAGING_RATE_LIMIT_PER_MINUTE` | Staging request limit per user | Tune for staging | Optional | `60` |
| `PRODUCTION_RATE_LIMIT_PER_MINUTE` | Production request limit per user | Tune for capacity/abuse policy | Optional | `30` |
| `DEV_MAX_QUESTION_TOKENS` | Development question token limit | Tune for local use | Optional | `4096` |
| `STAGING_MAX_QUESTION_TOKENS` | Staging question token limit | Tune for model/context | Optional | `2048` |
| `PRODUCTION_MAX_QUESTION_TOKENS` | Production question token limit | Tune for model/context | Optional | `2048` |
| `RATE_LIMIT_REDIS_TIMEOUT_SECONDS` | Redis connection/read timeout | Tune for the service | Optional | `0.5` |

## Security notes

- API keys stay server-side; rotate them regularly
- `.env` is git-ignored
- Dev-only auth mode is refused in production
- Generated SQL is validated by a parser and schema allowlist, then executed under a read-only database role
- PostgreSQL access uses an approved view and a tenant-scoped row-level security policy; SQLite adds the tenant predicate in application code
- Document passages are filtered by tenant and minimum role before ranking; Gemini embeddings are searched in Chroma and fused with SQLite BM25 results

## Document ingestion and semantic search

The included reporting documents are seeded automatically. To ingest `.txt` and `.md` files, first start the API once (or run `python -c "from app.ingestion.seed import initialize; initialize()"`), then run:

```powershell
python -m app.ingestion.documents .\my-documents --tenant-id local-dev-tenant --min-role viewer
```

Supported minimum roles are `viewer`, `analyst`, and `admin`. The tenant must match the authenticated tenant claim. Files are split into overlapping chunks and indexed in the local SQLite FTS table. Choose the minimum role deliberately; it controls which roles can retrieve the chunks. Re-running ingestion for the same directory synchronizes it: unchanged files remain idempotent, and changed or deleted source files have stale chunks removed from SQLite and Chroma.

To build the optional Chroma semantic index, configure `GEMINI_API_KEY` and then run:

```powershell
python -m app.ingestion.index_vectors
```

When vectors exist, search fuses Chroma semantic results with BM25 using reciprocal-rank fusion. Chroma stores its local index under `data/chroma/`; this persistent client is intended for local development and testing. For a deployed service, use a server-backed Chroma deployment and secure its network and access. If Gemini is not configured, the index has not been built, or semantic search fails, retrieval falls back to BM25. Document passages and their authoritative access metadata remain in SQLite even when sales data uses PostgreSQL.

## Testing

```bash
python -m pytest -q
python -m app.evaluation.run
```

The offline evaluation prints measured BM25 hit@3, supported workflow rate, SQL rejection rate, tenant/role enforcement checks, and p50/p95 local workflow latency. Change the number of runs with `python -m app.evaluation.run --iterations 20`. It disables Gemini calls so results are repeatable and do not consume API quota. LLM answer groundedness is not included in this offline score; that requires a labeled, human-reviewed live-model evaluation set.

One PostgreSQL integration test is skipped unless `TEST_POSTGRES_URL` is set to a migrated test database URL; that skip is expected.

### Latest local results

- Date: `2026-10-31`
- Python version: `3.12.3`
- Commit: `d9f6e85`
- pytest pass/skip counts: `42 passed, 1 skipped`
- hit@3: `100% (3/3)`
- SQL rejection rate: `100% (4/4)`
- p50: `3.78 ms`
- p95: `5.58 ms`

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

For local shared-limiter development, start Redis with `docker compose --profile shared-limits up -d redis` and set `RATE_LIMIT_REDIS_URL=redis://localhost:6379/0`. Production requires Redis; use a managed service secured with authentication, TLS, and network controls.

Gemini's free tier is suitable for development experiments, subject to current model quotas. Google marks free-tier prompts/responses as eligible for product improvement; avoid sending confidential or production data through a free-tier key. See the [Gemini API pricing and data-use details](https://ai.google.dev/gemini-api/docs/pricing) and [billing tiers](https://ai.google.dev/gemini-api/docs/billing).

## Project status

Actively under development. See the [manual](manual.md), [explanation](explanation.md) and the scope notes near the top of this README.


## Author

Vedika Girap · vedikagirap5@gmail.com
