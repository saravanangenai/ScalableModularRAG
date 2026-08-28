# Architecture — MM-RAG Platform

Current-state snapshot of the multi-tenant multimodal RAG platform. The authoritative
design lives in [`specs/architecture/`](specs/architecture/) — read
[`01-system-architecture.md`](specs/architecture/01-system-architecture.md) first. This file
is a rendered overview (Mermaid diagram + folder map) and is kept in sync as specs land.

Status legend: **built** = implemented and tested · **partial** = scaffolded, core paths
work, extensions pending · **planned** = directory stub only, waiting on its spec.

## System diagram

```mermaid
flowchart TB
    users([Users])

    subgraph clients [Client apps]
        webui["Web UI (Vue.js)<br/>apps/UI · planned"]
        admin["Streamlit admin<br/>apps/streamlit-admin · planned"]
    end

    subgraph api_layer [API layer]
        api["API Gateway / Auth (FastAPI)<br/>apps/api · built<br/>JWT verify · RBAC guards · routing<br/>routers: auth, tenants, workspaces, documents, jobs"]
    end

    subgraph services [Domain services — packages/*]
        ingestion["Ingestion Service<br/>packages/ingestion · built<br/>parse → chunk → embed → index · versioning"]
        parsing["Parser Workers<br/>packages/parsing · partial<br/>text / OCR / tables / images (vision captioning planned)"]
        retrieval["Retrieval Service<br/>packages/retrieval · planned<br/>dense + sparse · RRF fusion · rerank · mandatory ACL filter"]
        generation["Generation Service<br/>packages/generation · planned<br/>multimodal LLM · citation build"]
    end

    subgraph infra_layer [Infrastructure]
        queue["Job Queue<br/>Redis + Celery · built<br/>workers/celery_app.py"]
        storage["Object Storage (S3 / MinIO)<br/>packages/storage · built<br/>raw PDFs · extracted images"]
        qdrant["Qdrant<br/>vectors + filtered payload<br/>infra only"]
        reranker["Reranker<br/>cross-encoder · planned"]
        obs["Observability<br/>packages/observability · partial<br/>structlog built · OTel / Prometheus / Sentry planned"]
        pg[("PostgreSQL — packages/db · built<br/>users · tenants · workspaces · documents · versions<br/>ingestion_jobs · members · audit_log · Row-Level Security")]
    end

    users --> webui
    users --> admin
    webui -->|HTTPS / JSON (OpenAPI)| api
    admin -->|HTTPS / JSON (OpenAPI)| api

    api --> ingestion
    api --> retrieval
    api -->|chat / admin routes · planned| generation

    ingestion --> queue
    queue --> parsing
    ingestion --> storage
    ingestion --> pg
    parsing --> qdrant

    retrieval --> qdrant
    retrieval --> reranker
    reranker --> generation
    retrieval --> pg
    generation --> pg

    api --> pg
    api -.-> obs
    ingestion -.-> obs
    retrieval -.-> obs

    generation --> answer([Answer + citations])
```

### Boundary rules

- `apps/*` may import `packages/*` and call `apps/api` over HTTP. `packages/*` never imports
  from `apps/*` or from another app — this is what keeps ingestion / retrieval / generation
  reusable from the API, Celery workers, the admin tool, and `eval/`.
- `apps/UI` and `apps/streamlit-admin` are pure API clients: never touch Qdrant / Postgres
  directly, never hold provider API keys.
- Qdrant is a pure vector + payload store. The tenant / workspace / ACL filter is computed
  from Postgres-backed auth (never from client input) and applied to every query.

### Request flow

**Ingestion (async):** upload → `apps/api` documents router → write file to Object Storage →
create `document` / `version` / `ingestion_job` rows in Postgres → enqueue Celery job →
parser worker parses text / OCR / tables / images → chunk → embed (dense + sparse) → upsert
to Qdrant with ACL payload → job status → `ready` → UI polls status.

**Query (sync):** question → `apps/api` chat router (authenticated) → Retrieval builds the
mandatory tenant / workspace / ACL filter from the JWT → dense + sparse search in Qdrant →
RRF fusion → cross-encoder rerank → top-K → Generation assembles the multimodal prompt
(text context + retrieved images) → LLM call → answer + citations → persisted as a
conversation message in Postgres → returned to the UI.

## Folder structure

```text
mm-rag/  (05-Assignment-RAG-MMRAG)
├── CLAUDE.md                          # short orientation
├── ARCHITECTURE.md                    # this file
├── pyproject.toml / uv.lock           # Python 3.12, managed with uv
├── alembic.ini
│
├── specs/                             # spec-driven development record
│   ├── README.md                      # live per-spec status index
│   ├── architecture/                  # 01–09 living design docs (read 01 first)
│   │   ├── 01-system-architecture.md
│   │   ├── 02-data-model.md
│   │   ├── 03-ingestion-workflow.md
│   │   ├── 04-retrieval-design.md
│   │   ├── 05-multimodal-strategy.md
│   │   ├── 06-security-model.md
│   │   ├── 07-evaluation-observability.md
│   │   ├── 08-roadmap.md
│   │   └── 09-repo-and-module-structure.md
│   ├── templates/                     # spec / plan / tasks templates
│   ├── 010-metadata-db-and-object-storage/   {spec,plan,tasks}.md   [done]
│   ├── 011-auth-and-workspaces/              {spec,plan,tasks}.md   [done]
│   └── 020-async-ingestion-pipeline/         {spec,plan,tasks}.md   [done]
│
├── apps/
│   ├── api/                           # built — FastAPI backend, the only thing UIs talk to
│   │   ├── main.py
│   │   ├── routers/                   # auth, tenants, workspaces, documents, jobs
│   │   ├── deps/                      # auth.py, db.py, rbac.py — guards, tenant resolution
│   │   └── schemas/                   # api_keys, documents, jobs, members, tenants
│   ├── UI/                            # planned — Vue.js public product UI (stub)
│   └── streamlit-admin/              # planned — internal/admin tool (stub)
│
├── packages/                          # shared business logic (never imports apps/*)
│   ├── db/                            # built — SQLAlchemy models + Alembic
│   │   ├── models.py
│   │   ├── session.py · config.py · audit.py
│   │   └── migrations/versions/       # 0001_initial_schema, 0002_…subject_unique,
│   │                                  #   0003_workspace_members_tenant_id
│   ├── storage/                       # built — object storage client (S3 / MinIO)
│   │   └── client.py · keys.py · config.py
│   ├── auth/                          # built — JWT, API keys, RBAC, request context
│   │   └── jwt.py · api_keys.py · rbac.py · context.py · config.py
│   ├── exceptions/                    # built — DocumentPortalException-style hierarchy
│   │   └── base · auth · db · storage · parsing · ingestion
│   ├── observability/                 # partial — structured_logging.py (structlog); OTel pending
│   ├── parsing/                       # partial — pdf_parser.py (text/OCR/tables/images; vision pending)
│   ├── ingestion/                     # built — pipeline.py, versioning.py, qdrant_setup.py, config.py
│   ├── retrieval/                     # planned — stub (Phase 5)
│   └── generation/                    # planned — stub (Phase 5–6)
│
├── workers/
│   └── celery_app.py                  # built — Celery app + ingestion task definitions
│
├── scripts/
│   └── setup_keycloak_dev.py          # built — local IdP bootstrap
│
├── postman/                           # built — auth collection + local environment
│
├── infra/
│   ├── docker-compose.yml             # built — postgres, redis, qdrant, minio, api, worker
│   └── .env.example
│
├── eval/
│   ├── datasets/                      # planned — golden dataset (Phase 7)
│   └── reports/                       # planned
│
├── prompt_library/                    # planned — single source of prompts
│
└── tests/
    ├── unit/                          # built — auth, db, storage, parsing, ingestion,
    │                                  #   observability, exceptions
    ├── integration/                   # built — auth flow, JIT provisioning, RLS, RBAC routes,
    │                                  #   api keys, audit log, upload + ingest, versioning,
    │                                  #   storage/db roundtrip, tenant/workspace lifecycle
    └── fixtures/sample.pdf
```

## Roadmap position

| Phase | Scope | Status |
|---|---|---|
| 0 — Foundations | Spec set, `.claude` workflow, repo scaffold | done |
| 1 — V1 prototype | Streamlit + local pipeline (separate sibling repo) | baseline |
| 2 — Metadata DB + Object Storage + Auth | `packages/db`, `packages/storage`, `packages/auth`, `apps/api` auth/tenant/workspace/document routes, RLS | done |
| 3 — Async ingestion | `packages/parsing`, `packages/ingestion`, Celery + Redis, job status endpoints | done |
| 4 — Tenant/RBAC filtering | Mandatory retrieval-time filter, RBAC route guards, authorization test suite | planned |
| 5 — Hybrid retrieval + reranking | Dense + sparse + RRF + cross-encoder rerank | planned |
| 6 — Better multimodal retrieval | Vision captioning, table intelligence | planned |
| 7 — Evaluation + observability | Golden eval dataset, eval CLI, OpenTelemetry, Prometheus/Grafana, Sentry | planned |
| 8 — Production API + frontend | `apps/UI`, hardened `apps/api`, `apps/streamlit-admin` migrated off `src/*` | planned |
| 9 — Enterprise integrations + billing | Connectors (Drive/SharePoint/S3), quota enforcement, billing, audit UI | planned |

See [`specs/architecture/08-roadmap.md`](specs/architecture/08-roadmap.md) for why the phases
are ordered this way.
