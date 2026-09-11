# System Architecture — MM-RAG Platform

- **Status:** approved baseline (living doc — update in place as specs land)
- **Supersedes:** V1 prototype (`ui/app.py` calling `src/*` in-process)

> ⚠️ **Single-tenant as-built ([`specs/012`](../012-single-tenant-simplification/spec.md)).**
> Wherever this doc says "tenant/workspace/ACL" or lists `tenants`/`quotas`, read it as
> workspace-scoped: no tenant tables, no `tenant_id` payload field, no RLS. Multi-tenancy is
> the deferred target (roadmap Phase 10).

## 1. Where we start

Today the entire system is one Python process. `ui/app.py` (Streamlit) imports
`src/parsing.py`, `src/ingestion.py`, `src/retriever.py`, and `src/generation.py` directly
and calls them synchronously on the Streamlit thread. There is no API, no auth, no
multi-user concept, no job queue, and all files live on local disk under `data/`. This is
Phase 1 in `08-roadmap.md`.

Everything below describes the target architecture we are migrating to, phase by phase.
Nothing here is implemented yet unless a linked spec under `specs/<NNN-slug>/` says so.

## 2. Target architecture

```
                                   USERS
                                     |
                        +------------------------+
                        |   Web UI (Next.js)     |   Streamlit (internal/admin)
                        |   apps/web             |   apps/streamlit-admin
                        +------------------------+
                                     |  HTTPS/JSON (OpenAPI)
                                     v
                        +------------------------+
                        |   API Gateway / Auth    |   apps/api  (FastAPI)
                        |   - JWT verification    |
                        |   - rate limiting       |
                        |   - request routing     |
                        +------------------------+
                          |          |           |
             +------------+   +-----+-----+   +--+---------------+
             |                |           |    |                  |
             v                v           v    v                  v
     Document API       Chat/Query API  Admin API           Webhook/Connector API
     (upload, list,     (ask, sources,  (usage, audit,      (future: Drive/SharePoint
      versions)          feedback)       quotas)             ingestion triggers)
             |                |
             v                v
     +---------------+  +------------------+
     | Ingestion      |  | Retrieval        |
     | Service        |  | Service          |
     | (packages/     |  | (packages/       |
     |  ingestion)    |  |  retrieval)      |
     +---------------+  +------------------+
             |                   |  fan-out: dense + sparse search
             v                   v
     +---------------+   +------------------+
     | Object Storage |   | Qdrant           |
     | (S3 / MinIO)   |   | (vectors +       |
     |  raw PDFs,     |   |  searchable      |
     |  extracted     |   |  payload)        |
     |  images        |   +------------------+
     +---------------+            |
             ^                    v
             |            +------------------+
     +---------------+    | Reranker         |
     | Job Queue      |    | (cross-encoder / |
     | (Redis +       |    |  Cohere Rerank)  |
     |  Celery)       |    +------------------+
     +---------------+            |
             |                    v
             v            +------------------+
     +---------------+    | Generation       |
     | Parser Workers |    | Service          |
     | (packages/     |    | (packages/       |
     |  parsing)      |    |  generation)     |
     | - text/OCR     |    | - multimodal LLM |
     | - tables       |    | - citation build |
     | - vision       |    +------------------+
     |   captioning   |            |
     | - embeddings   |            v
     +---------------+     Answer + Citations
             |                    ^
             v                    |
     +----------------------------+-------+
     |     Metadata / ACL Database          |
     |     (PostgreSQL)                     |
     |     users, tenants, workspaces,       |
     |     documents, versions, jobs,        |
     |     conversations, permissions, audit |
     +---------------------------------------+
                          ^
                          |
                +--------------------+
                | Observability       |
                | (OpenTelemetry,     |
                |  Langfuse/Phoenix,  |
                |  Prometheus/Grafana,|
                |  Sentry)            |
                +--------------------+
```

This is the same shape as the assignment's target diagram, made concrete against this
repo's code and naming.

## 3. Component responsibility table

| Component | Responsibility | Owns | Current repo mapping | Scales independently because |
|---|---|---|---|---|
| **Web UI** (`apps/web`, Next.js) | Public-facing product UI: workspaces, chat, source/page preview, sharing, feedback | Nothing durable — calls the API for everything | New (assignment 3.1); replaces Streamlit as the public surface | Stateless SPA/SSR; scales with CDN + edge, independent of backend load |
| **Streamlit admin** (`apps/streamlit-admin`) | Internal/demo tool for parsing inspection, manual re-ingestion, debugging | Nothing durable — calls the API, does not import `src/*` directly anymore | `ui/app.py`, rewired to call `apps/api` instead of the pipeline in-process | Low-traffic, single instance is fine |
| **API Gateway / Auth** (`apps/api`, FastAPI) | AuthN (JWT verification), authorization guards, request validation, routing to services, rate limiting, quota enforcement | No business logic beyond auth/routing | New; wraps `src/*` logic | Stateless — horizontal scale behind a load balancer |
| **Ingestion Service** (`packages/ingestion`) | Orchestrates parse -> chunk -> embed -> index for one document version; emits status transitions | Job state machine | `src/ingestion.py`, `src/parsing.py` | Scale worker count independently of API traffic; CPU/OCR-bound |
| **Parser Workers** | Execute one ingestion job: PDF text/OCR/table/image extraction, vision captioning, chunking, embedding | Nothing durable — writes through Ingestion Service | `src/parsing.py` (`ComplexPDFParser`) | Scale by queue depth; the expensive, spiky part of the system |
| **Retrieval Service** (`packages/retrieval`) | Dense + sparse search, RRF fusion, reranking, mandatory tenant/ACL filter injection | No durable state | `src/retriever.py` (`MultimodalQdrantRetriever`), extended | Scale with query volume; read-heavy, cacheable |
| **Generation Service** (`packages/generation`) | Prompt assembly, multimodal LLM call, citation formatting, usage/cost capture | No durable state | `src/generation.py` (`MultimodalRAGGenerator`) | Scale independently — bound by LLM provider latency/cost, not DB |
| **Object Storage** (S3/MinIO) | Durable storage for original PDFs and extracted images | Binary files only, addressed by content hash | `data/uploads/`, `data/parsed_pdf_output/**/extracted_images` | Scales natively (managed service) |
| **Job Queue** (Redis + Celery) | Decouples upload from processing; retries, dead-lettering, status events | Job records (durable copy lives in Postgres `ingestion_jobs`) | None today (Streamlit blocks synchronously) | Scale broker + worker pool independently |
| **Qdrant** | Vector similarity + payload-filtered search, hybrid (dense+sparse) storage | Chunk vectors + payload (tenant/workspace/doc/version/ACL/content_type) | Same Qdrant collection, extended payload schema | Scale via sharding/replicas as vector count grows |
| **PostgreSQL** | System of record for users, tenants, workspaces, documents, versions, jobs, conversations, permissions, audit log, quotas | Everything relational; Qdrant payload is a denormalized projection of a subset of this | None today (no metadata DB) | Vertical scale + read replicas; not on the hot generation path |
| **Observability stack** | Tracing (per-request and per-LLM-call), metrics, error tracking, eval dashboards | Traces/metrics/logs only | `logger/custom_logger.py` (structlog to file) is the seed; extended | Scales independently (managed/self-hosted observability backend) |

## 4. Request/data flow

**Ingestion (async):**
`Upload (Web UI) -> Document API (apps/api) -> write file to Object Storage -> create
document/version/job rows in Postgres -> enqueue job (Celery/Redis) -> Parser Worker picks
up job -> parses text/OCR/tables/images -> vision-captions images -> chunks text ->
embeds (dense + sparse) -> upserts into Qdrant with tenant/workspace/ACL payload -> updates
job status to ready in Postgres -> Web UI polls/subscribes to status.`

**Query (sync, low-latency):**
`User question (Web UI) -> Chat API (apps/api, authenticated) -> Retrieval Service builds a
mandatory tenant/workspace/ACL filter from the JWT (never from client input) -> dense search
+ sparse search in Qdrant -> RRF fusion -> cross-encoder rerank -> top-K -> Generation
Service assembles multimodal prompt (text context + retrieved images) -> LLM call ->
answer + citations -> persisted as a conversation message in Postgres -> returned to UI.`

## 5. Why service boundaries are drawn here

- **Ingestion vs. Retrieval vs. Generation are separate packages, not one `src/`,** because
  they scale differently (ingestion is CPU/OCR-bound and spiky, retrieval is
  latency-sensitive and read-heavy, generation is bound by LLM provider limits/cost) and
  because ingestion is the only one that needs to run outside the request/response cycle.
- **API is a thin gateway, not where business logic lives,** so the same ingestion/retrieval/
  generation packages can be called from the API, from Celery workers, from the Streamlit
  admin tool, and from a future CLI/batch-eval harness without duplicating logic — this is
  what `09-repo-and-module-structure.md` calls the "package boundary rule."
- **Qdrant stays a pure vector/payload store; Postgres is the source of truth for identity,
  ownership, and permissions.** Filters used at query time are derived from Postgres-backed
  auth, then applied to Qdrant — Qdrant is never asked "what can this user see," only "match
  these tenant/workspace/ACL values," which the API computes.

## 6. Related docs

- `02-data-model.md` — the Postgres schema and Qdrant payload schema referenced above
- `03-ingestion-workflow.md` — the job state machine in detail
- `04-retrieval-design.md` — the dense+sparse+RRF+rerank pipeline in detail
- `06-security-model.md` — how the mandatory retrieval filter is derived and enforced
- `09-repo-and-module-structure.md` — the actual folder layout implementing this diagram
