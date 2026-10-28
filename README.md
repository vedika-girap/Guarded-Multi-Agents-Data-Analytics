# Guarded Multi-Agent Analytics

A GenAI analytics backend where users ask business questions in plain English and a team of LLM agents answers them from **SQL data** and **internal documents**, while enforcing who is allowed to see what.

Most NL-to-SQL and RAG demos ignore security. This project treats **authorization, safety, and evaluation** as first-class features instead of afterthoughts.

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

Python, FastAPI, LangGraph, OpenAI API, SQLite (demo) / PostgreSQL (production), FAISS, Alembic, pytest, Docker, GitHub Actions


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

## Configuration

All settings live in `.env` (never commit this file). Every variable is documented in `.env.example`.

| Variable | Purpose | Where to get it | Required |
|---|---|---|---|
| `OPENAI_API_KEY` | LLM access | platform.openai.com, API keys | Yes |
| `OPENAI_MODEL` | Model name | OpenAI model list | Has default |
| `ENVIRONMENT` | `development`, `staging` or `production` | You choose | Has default |

<Add rows as each stage introduces new variables.>

## Security notes

- API keys stay server-side; rotate them regularly
- `.env` is git-ignored
- Dev-only auth mode is refused in production
- Generated SQL is validated by a parser and schema allowlist, then executed under a read-only database role

## Testing

```bash
pytest
```

## Project status

Actively under development. See the roadmap above.



## Author

Vedika Girap · vedikagirap5@gmail.com
