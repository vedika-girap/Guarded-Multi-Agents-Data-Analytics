# Code Flow and Current Architecture

This document describes the current implementation after Stage 4. It is a FastAPI analytics service with optional Gemini generation and embeddings, local SQLite document search, and a PostgreSQL backend for structured data when configured.

## Architecture

```text
API client / FastAPI docs
          |
          v
FastAPI (`app/main.py`)
  |- configuration validation and request IDs
  |- SQLite document/demo initialization
  `- POST /ask (`app/api/routes.py`)
       |- fixed dev identity or verified HS256 JWT (`app/auth`)
       |- per-user request rate and token limits
       `- LangGraph (`app/graph/workflow.py`)
            |- discover intent with Gemini or deterministic rules
            |- retrieve tenant/role-filtered SQLite FTS5 BM25 passages
            |- optionally fuse Gemini embeddings ranked by Chroma
            |- generate SQL with Gemini or reviewed templates
            |- validate SQL with SQLGlot
            |- execute read-only with tenant and role policy
            `- synthesize and check answer evidence with Gemini

Structured data: DATABASE_URL -> SQLite demo OR PostgreSQL sales view + RLS
Documents: local SQLite FTS5 store with tenant/minimum-role metadata; optional persistent Chroma index
```

## Startup and settings

Pydantic Settings loads `.env` through `python-dotenv`, with process environment variables taking precedence. The app defaults to development mode, fixed local viewer auth, SQLite at `data/demo.db`, and no required model key. `GEMINI_MODEL` defaults to `gemini-3.8-flash`; `GEMINI_EMBEDDING_MODEL` defaults to `gemini-embedding-001`.

On startup, the FastAPI lifespan validates configuration and seeds the local SQLite demo/document store. If `DATABASE_URL` points to PostgreSQL, Alembic migrations are run separately by the operator; app startup does not perform DDL or auto-migrate production data.

## Request flow

### 1. Request ID, identity, and limits

Middleware assigns a request ID and adds it to response headers. API errors include `error_code`, `message`, and `request_id`.

`current_identity` returns a fixed `local-dev-user` / `local-dev-tenant` viewer identity when `AUTH_MODE=dev`. `X-Role` is ignored. In JWT mode, the app verifies an HS256 Bearer token's signature, issuer, audience, expiry, and required `sub`, `tenant_id`, and `role` claims. Only `viewer`, `analyst`, and `admin` roles are accepted.

Before graph execution, the request limit layer checks the question's Gemini tokenizer count and applies a per-user rolling request limit configured for development, staging, or production. Local development uses an in-process counter. When `RATE_LIMIT_REDIS_URL` is configured, an atomic Redis sliding window shares the quota across workers and replicas. Production configuration requires Redis, and requests fail closed with 503 if the configured limiter is unavailable.

### 2. Intent discovery

The `discover` LangGraph node calls Gemini Interactions API for a schema-constrained route when `GEMINI_API_KEY` is set. It classifies questions as documents, data, hybrid, or unsupported. With no model key, small deterministic rules choose between document retrieval, the approved SQL templates, and unsupported.

### 3. Document retrieval

`retrieve` passes the verified tenant and role to `search_documents()` in `app/retrieval/search.py`. SQLite FTS5 filters by tenant and minimum role before BM25 ranking. If Gemini vectors have been indexed, Chroma's metadata filter applies tenant and minimum-role criteria during vector retrieval; results are rechecked against the authoritative SQLite metadata and fused with BM25 by reciprocal rank. Without Chroma vectors or when embeddings fail, retrieval falls back to BM25. Documents remain in the local SQLite store even when the sales database uses PostgreSQL.

Plain text and Markdown documents can be chunked and ingested with `python -m app.ingestion.documents <directory> --tenant-id <id> --min-role <role>`. Re-running ingestion on the same source directory synchronizes changed and deleted chunks. `python -m app.ingestion.index_vectors` builds optional Chroma vectors and requires a Gemini API key. The persistent local Chroma client is for development/testing; use a secured Chroma server for deployed multi-user use.

### 4. SQL generation and validation

For data questions, the graph asks Gemini for a SQL query or uses a reviewed template when running without a Gemini key. SQLGlot rejects writes, multiple statements, unapproved tables/columns/functions, and wildcard projections that could expose internal tenant IDs. Viewer queries must aggregate and receive a `HAVING COUNT(*) >= VIEWER_MIN_GROUP_SIZE` suppression condition.

### 5. Database selection and tenant enforcement

`execute_sql()` uses the `DATABASE_URL` backend:

- **SQLite (default):** opens the database read-only, enables query-only mode, adds a parameterized `tenant_id` predicate from verified identity, applies a progress handler, and hard-caps returned rows.
- **PostgreSQL:** sets a read-only transaction, `statement_timeout`, and transaction-local `app.tenant_id` / `app.user_role` settings. The `sales` view reads from `sales_data`, where RLS is enabled and forced with a default-deny policy. The application login is a non-superuser read-only role; a separate non-login role owns the view and is subject to the table policy.

PostgreSQL DDL and demo data are installed with `alembic upgrade head`. The Compose init script provisions the database roles. The migration connection should use a trusted owner/admin URL; runtime requests use the restricted app login URL.

### 6. Answer and evidence

When Gemini is available and the graph has evidence, it synthesizes an answer and makes a second structured evidence-check request. Without Gemini, it returns evidence-shaped document text or SQL rows. The API response contains the answer, route, evidence, limitations, latency, and `llm_used`.

## Provider failure handling and workflow timing

Gemini SDK failures are converted into stable categories before they reach the graph. The API exposes safe status labels and failure categories, while user-facing limitations describe fallback behavior without returning provider response text. The graph records elapsed milliseconds for each node that ran, and request logs include the request ID and timings. Logs omit questions, SQL rows, evidence, and provider error bodies.

## Current modules

| Area | Implementation |
|---|---|
| API and errors | FastAPI, request IDs, JSON errors, `/ask`, `/health` |
| Auth | Fixed development identity or HS256 JWT with issuer/audience checks |
| Limits | Per-environment question token ceiling and per-user sliding window (in-process locally, shared Redis when configured) |
| Orchestration | LangGraph discover, retrieve, SQL, and answer nodes |
| Model | Google Gemini Interactions API with structured output; optional key |
| Documents | SQLite FTS5 BM25, offline text/Markdown chunk ingestion, tenant/minimum-role filters, optional Gemini vectors in Chroma with hybrid ranking |
| SQL safety | SQLGlot AST allowlist, no wildcard projection, read-only execution, row cap |
| SQLite | Local demo database with application tenant predicate |
| PostgreSQL | Alembic schema, approved view, restricted app role, transaction-local RLS settings |
| Evaluation | Deterministic offline report for retrieval hit@3, workflow evidence success, SQL rejection, tenant/viewer checks, and p50/p95 latency; separate tests and optional PostgreSQL integration |
| Logs | Request-correlated structured role, route, latency, model status, provider categories, and node timings; no prompt/evidence/provider-body logging |

## Current limits

- PostgreSQL cross-tenant enforcement requires migrations and a correctly configured restricted runtime role.
- The optional PostgreSQL integration test needs `TEST_POSTGRES_URL`; otherwise it is skipped.
- Local rate limiting is process-local. Production configuration requires the shared Redis limiter; use a managed, authenticated Redis service and secure its network access.
- Document ingestion and vector refresh are run manually; background scheduling and production corpus operations remain future work.
- The evaluation corpus is synthetic and small; the offline workflow score measures route/evidence presence, not answer groundedness. Live groundedness needs labeled human review.
- Gemini failures use stable categories and safe fallbacks; retries, circuit breaking, dashboards, and alert thresholds remain future operational work.
