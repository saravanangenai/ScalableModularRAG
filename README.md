# MM-RAG Platform

A multi-tenant, production-grade **multimodal RAG platform over PDFs** — text, OCR, tables,
and images — built as a modular monorepo: multiple deployable apps, shared business logic in
internal `packages/*`, service boundaries enforced as import boundaries.

The single-process Streamlit prototype it replaces lives in a separate sibling repo; nothing
has been ported in directly — see
[`specs/architecture/09-repo-and-module-structure.md`](specs/architecture/09-repo-and-module-structure.md) §3.

## Documentation

| Start here | For |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Mermaid system diagram, annotated folder map, roadmap status |
| [`specs/architecture/01-system-architecture.md`](specs/architecture/01-system-architecture.md) | Full component design, responsibilities, request/data flow |
| [`specs/architecture/08-roadmap.md`](specs/architecture/08-roadmap.md) | Phased plan — what ships when, and why in that order |
| [`specs/README.md`](specs/README.md) | Per-spec status index |
| [`CLAUDE.md`](CLAUDE.md) | Short orientation + conventions |

## Current state

Phases 0–3 of the roadmap are implemented:

- **Metadata DB** (`packages/db`) — PostgreSQL schema, SQLAlchemy models, Alembic migrations,
  Row-Level Security for tenant isolation.
- **Object storage** (`packages/storage`) — S3 / MinIO client for raw PDFs and extracted images.
- **Auth & workspaces** (`packages/auth`, `apps/api`) — Keycloak-backed JWT verification, API
  keys, RBAC guards, tenant / workspace membership; routers for `auth`, `tenants`,
  `workspaces`, `documents`, `jobs`.
- **Async ingestion** (`packages/parsing`, `packages/ingestion`, `workers/celery_app.py`) —
  Celery + Redis queue, parser workers (text / OCR / tables / images), job status endpoints,
  content-hash versioning, Qdrant collection setup.

Not yet built: tenant/RBAC retrieval filtering, hybrid retrieval + reranking, vision
captioning & table intelligence, evaluation + full observability, the Vue.js frontend.
`packages/retrieval` and `packages/generation` are stubs. See [`ARCHITECTURE.md`](ARCHITECTURE.md)
for the per-package breakdown.

## Quick start

Requires Python 3.12, [`uv`](https://docs.astral.sh/uv/), and Docker.

```bash
# 1. Backing services (Postgres, Redis, Qdrant, MinIO, Keycloak)
cp infra/.env.example infra/.env          # then edit secrets
cd infra && docker compose --env-file .env up -d && cd ..

# 2. Python environment
uv sync

# 3. Database schema
uv run alembic upgrade head

# 4. Bootstrap the local Keycloak realm / client / test users
uv run python scripts/setup_keycloak_dev.py

# 5. API
uv run uvicorn apps.api.main:app --reload

# 6. Ingestion worker (separate terminal)
uv run celery -A workers.celery_app worker --loglevel=info
```

Provider keys (e.g. `OPENAI_API_KEY`) go in `infra/.env` and are read by the Celery worker
only, never by the `apps/api` request path — see
[`specs/architecture/06-security-model.md`](specs/architecture/06-security-model.md) §6.
`infra/.env` is gitignored; never commit it.

## Tests

```bash
uv run pytest                    # all
uv run pytest tests/unit         # per-package unit tests
uv run pytest tests/integration  # cross-service (RLS, RBAC, upload+ingest, ...)
```

The Postman collection under [`postman/`](postman/) exercises the auth flow against a running API.

## How work happens here

Spec-driven. No implementation starts without an approved spec: `spec.md` → `plan.md` →
`tasks.md` under `specs/<NNN-slug>/`, driven by the `spec` skill. Anything touching an API
contract, the data model, retrieval behavior, or security/tenancy goes through the full
workflow. See [`CLAUDE.md`](CLAUDE.md) and [`.claude/skills/spec/SKILL.md`](.claude/skills/spec/SKILL.md).

## Conventions

- Python 3.12, managed with `uv`.
- Structured logging via `structlog` (`packages/observability`) — events as
  `snake_case_event_name` with keyword fields.
- Exceptions wrapped and re-raised as `DocumentPortalException`-style types at module
  boundaries (`packages/exceptions`).
- `apps/*` may import `packages/*` and call `apps/api` over HTTP; `packages/*` never imports
  from `apps/*`. `apps/UI` and `apps/streamlit-admin` are pure API clients and never hold
  provider API keys.
