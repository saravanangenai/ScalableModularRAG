# Repo & Module Structure

- **Status:** approved baseline

> ⚠️ **Single-tenant as-built ([`specs/012`](../012-single-tenant-simplification/spec.md)).**
> Read "tenant/workspace/ACL" below as "workspace/ACL"; there is no tenant layer, no RLS GUC,
> and no `/tenants/*` routes. §4's `admin`/`auth` rows are updated accordingly. Multi-tenancy
> is the deferred target (roadmap Phase 10).
- **Decision:** monorepo, multiple deployable apps, shared logic in versioned internal
  packages. Not fully separate git repos (simpler local dev, still enforces service
  boundaries via package boundaries); not a single flat `src/` (current V1 problem — the UI
  imports pipeline internals directly).

## 1. Target layout

```
mm-rag/
├── .claude/
│   └── skills/spec/SKILL.md         # spec-driven workflow (this document set's process)
├── specs/                            # this directory
├── apps/
│   ├── api/                          # FastAPI backend — the only thing apps/UI and
│   │   ├── main.py                   # apps/streamlit-admin are allowed to talk to
│   │   ├── routers/
│   │   │   ├── documents.py          # upload, list, get, delete, versions
│   │   │   ├── jobs.py                # ingestion job status (poll/SSE)
│   │   │   ├── chat.py                # ask, conversation history, sources
│   │   │   ├── feedback.py            # thumbs up/down
│   │   │   ├── admin.py               # usage, audit, quotas
│   │   │   └── auth.py                # token exchange / api-key management
│   │   ├── deps/                      # auth guards, tenant/workspace resolution
│   │   ├── schemas/                   # pydantic request/response models (the API contract)
│   │   └── settings.py
│   ├── UI/                           # React SPA (Vite) — public product UI (assignment 3.1)
│   │   ├── src/
│   │   │   ├── auth/                  # AuthProvider (OIDC+PKCE via mm-rag-ui client),
│   │   │   │                          # RequireAuth route guard
│   │   │   ├── api/                   # typed fetch wrapper + one module per apps/api
│   │   │   │                          # resource (workspaces/documents/jobs/search/members)
│   │   │   ├── pages/                 # WorkspaceListPage, WorkspacePage (Documents/
│   │   │   │                          # Members/Search tabs), LoginCallback
│   │   │   └── components/            # ResultCard (content-type-aware), JobStatusBadge
│   │   └── (Vite + React + React Router + TanStack Query + Mantine; calls apps/api only,
│   │      never Qdrant/Postgres directly, never holds provider API keys; static `vite
│   │      build` output only — no Node server needed at runtime — specs/
│   │      071-search-frontend)
│   └── streamlit-admin/               # what ui/app.py becomes: internal/demo tool
│       └── app.py                     # calls apps/api over HTTP, no direct src/* imports
├── packages/                          # shared business logic — importable by apps/api,
│   │                                    Celery workers, apps/streamlit-admin (if needed),
│   │                                    and eval/, but never the other direction
│   ├── parsing/                       # was src/parsing.py
│   │   └── pdf_parser.py              # ComplexPDFParser, extended with vision captioning
│   ├── ingestion/                     # was src/ingestion.py
│   │   ├── pipeline.py                # orchestrates parse->chunk->embed->index
│   │   └── versioning.py              # content-hash / version-diff logic
│   ├── retrieval/                     # was src/retriever.py
│   │   ├── dense.py
│   │   ├── sparse.py
│   │   ├── fusion.py                  # RRF
│   │   ├── rerank.py
│   │   └── filters.py                 # mandatory tenant/workspace/ACL filter construction
│   ├── generation/                    # was src/generation.py
│   │   └── multimodal_rag.py
│   ├── db/                            # SQLAlchemy models + Alembic migrations (02-data-model.md)
│   │   ├── models.py
│   │   └── migrations/
│   ├── storage/                       # object storage client (S3/MinIO), local-disk shim for dev
│   ├── auth/                          # JWT verification, RBAC guard helpers (06-security-model.md)
│   ├── observability/                 # OpenTelemetry setup, structlog config (was logger/)
│   └── exceptions/                    # was exception/custom_exception.py
├── workers/
│   └── celery_app.py                  # Celery app + task definitions, imports packages/ingestion
├── eval/
│   ├── datasets/*.jsonl                # 07-evaluation-observability.md golden dataset
│   ├── reports/                        # eval run outputs, gitignored or archived per policy
│   └── run.py
├── infra/
│   ├── docker-compose.yml              # local dev: postgres, redis, qdrant, minio, api, worker
│   └── migrations/ (if not colocated in packages/db)
├── prompt_library/                     # unchanged location, still the single source of prompts
├── tests/
│   ├── unit/                           # per-package
│   └── integration/                    # cross-service (e.g. tenant-isolation authorization tests)
├── CLAUDE.md
└── README.md
```

## 2. The rule that keeps this modular

**`apps/*` may import from `packages/*` and call `apps/api` over HTTP. `packages/*` never
imports from `apps/*` or from another app's router/schema code.** This is what makes
`packages/ingestion`, `packages/retrieval`, and `packages/generation` independently reusable
from `apps/api`, `workers/celery_app.py`, `eval/run.py`, and (if ever needed) a CLI — the
same rule `01-system-architecture.md` §5 states architecturally, expressed here as an import
boundary that can be lint-enforced (e.g. an import-linter/`tach` config as a follow-up spec).

`apps/UI` and `apps/streamlit-admin` never import `packages/*` directly and never hold
provider API keys (OpenAI, Qdrant) — they are pure API clients. This is what makes "separate
project for UI" actually true rather than nominal: today `ui/app.py` imports `src/parsing.py`
et al. directly, which is exactly the coupling this structure removes.

## 3. Mapping from the current repo

| Today | Becomes |
|---|---|
| `src/parsing.py` | `packages/parsing/pdf_parser.py` |
| `src/ingestion.py` | `packages/ingestion/pipeline.py` + `packages/ingestion/versioning.py` |
| `src/retriever.py` | `packages/retrieval/*` (split into dense/sparse/fusion/rerank/filters) |
| `src/generation.py` | `packages/generation/multimodal_rag.py` |
| `ui/app.py` | `apps/streamlit-admin/app.py`, rewired to call `apps/api` |
| `exception/custom_exception.py` | `packages/exceptions/` |
| `logger/custom_logger.py` | `packages/observability/` (extended with OTel) |
| `prompt_library/prompt.py` | unchanged location |
| *(none)* | `apps/api`, `apps/UI`, `workers/`, `eval/`, `packages/db`, `packages/storage`, `packages/auth` — all new |

This mapping is the concrete migration checklist that Phase 2-3 specs
(`08-roadmap.md`) will turn into `tasks.md` entries — nothing above is executed until the
corresponding spec is written and approved.

## 4. API endpoint inventory (contract-level, detail lives in each phase's `plan.md`)

| Router | Endpoints (indicative) | Auth |
|---|---|---|
| `documents` | `POST /workspaces/{id}/documents` (upload), `GET /workspaces/{id}/documents`, `GET /workspaces/{id}/documents/{document_id}`, `GET /workspaces/{id}/documents/{document_id}/versions`, `DELETE /workspaces/{id}/documents/{document_id}` | workspace editor+ for write, viewer+ for read |
| `jobs` | `GET /workspaces/{id}/jobs/{job_id}`, `GET /workspaces/{id}/jobs/{job_id}/events` (SSE) | same workspace as the job's document — **note:** all document/job routes are nested under `/workspaces/{id}/...` (changed from an earlier bare `/documents/{id}`/`/jobs/{id}` shape by `020-async-ingestion-pipeline/plan.md`) because `documents`/`ingestion_jobs` are RLS-protected — resolving a bare id to its workspace/tenant would require querying the very table RLS is blocking before the GUC is set |
| `chat` | `POST /workspaces/{id}/conversations`, `POST /conversations/{id}/messages` (ask), `GET /conversations/{id}` | workspace viewer+ |
| `feedback` | `POST /messages/{id}/feedback` | workspace viewer+ |
| `workspaces` | `POST /workspaces`, `GET /workspaces`, `POST /workspaces/{id}/members`, `PATCH`/`DELETE /workspaces/{id}/members/{user_id}` | any authenticated user to create (becomes `owner`); workspace `owner` for membership changes |
| `api_keys` | `POST /workspaces/{id}/api-keys`, `GET /workspaces/{id}/api-keys`, `DELETE /workspaces/{id}/api-keys/{key_id}` | workspace `owner` |
| `admin` ⚠️ DEFERRED | `GET /tenants/{id}/usage`, `GET /tenants/{id}/audit-log` | tenant admin+ (Phase 10) |

## 5. Related docs

- `01-system-architecture.md` — the runtime shape this repo layout implements
- `08-roadmap.md` — when each app/package gets built
