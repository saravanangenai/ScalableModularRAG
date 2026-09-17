# Specs Index

This directory is the spec-driven development record for the MM-RAG platform. See
`.claude/skills/spec/SKILL.md` for the process. Read `architecture/01-system-architecture.md`
first — everything else builds on it.

## Architecture (living design docs — cross-cutting, not per-feature)

| Doc | Covers | Assignment section(s) |
|---|---|---|
| [01-system-architecture.md](architecture/01-system-architecture.md) | Component diagram, responsibilities, request/data flow, scaling | 3.1, §4, §8 (architecture diagram, component table) |
| [02-data-model.md](architecture/02-data-model.md) | Postgres schema + Qdrant payload schema, multi-tenant | 3.3, 3.4, §8 (data model) |
| [03-ingestion-workflow.md](architecture/03-ingestion-workflow.md) | Async ingestion state machine, retries, versioning | 3.2, 3.9, §8 (ingestion workflow, versioning) |
| [04-retrieval-design.md](architecture/04-retrieval-design.md) | Dense+sparse+RRF+rerank pipeline | 3.6, §8 (retrieval design) |
| [05-multimodal-strategy.md](architecture/05-multimodal-strategy.md) | Image vision captioning, table intelligence | 3.7, 3.8, §8 (image/table strategy) |
| [06-security-model.md](architecture/06-security-model.md) | AuthN, AuthZ, tenant isolation, secrets, audit | 3.4, 3.5, §8 (security model) |
| [07-evaluation-observability.md](architecture/07-evaluation-observability.md) | Eval framework, metrics, tracing, dashboards | 3.10, §8 (evaluation/observability) |
| [08-roadmap.md](architecture/08-roadmap.md) | Phased plan, dependencies, what's built first and why | §6, §8 (roadmap) |
| [09-repo-and-module-structure.md](architecture/09-repo-and-module-structure.md) | Monorepo layout, package boundaries, API endpoint inventory | 3.1, §8 (component responsibility) |

## Rubric coverage map

| Rubric area (assignment §8) | Marks | Primary doc(s) |
|---|---|---|
| Architecture & Service Separation | 20 | `01-system-architecture.md`, `09-repo-and-module-structure.md` |
| Ingestion & Storage Design | 15 | `02-data-model.md`, `03-ingestion-workflow.md` |
| Security & Multi-Tenancy | 15 | `02-data-model.md` §2-3, `06-security-model.md` |
| Retrieval Quality | 15 | `04-retrieval-design.md` |
| Multimodal Design | 10 | `05-multimodal-strategy.md` |
| Evaluation & Observability | 15 | `07-evaluation-observability.md` |
| Roadmap & Product Thinking | 10 | `08-roadmap.md` |

## Per-increment specs

Per `08-roadmap.md`'s phased plan:

| ID | Title | Status |
|---|---|---|
| `010-metadata-db-and-object-storage` | Postgres schema + migrations, S3/MinIO wiring | done |
| `011-auth-and-workspaces` | IdP integration, tenant/workspace membership, API auth middleware (tenancy parts superseded by `012`) | done |
| `012-single-tenant-simplification` | Dropped the tenant layer; kept IdP login + workspace RBAC. Amends `010`/`011`/`020` | done |
| `020-async-ingestion-pipeline` | Celery/Redis job queue, parser workers, status endpoints | done |
| `030-workspace-rbac-filtering` | Workspace-scoped Postgres RLS, dense-only `packages/retrieval` + search route with a mandatory server-constructed `workspace_id` filter, RBAC guard audit, retrieval authorization test suite | done |
| `040-hybrid-retrieval-reranking` | Sparse (BM25) search leg, Reciprocal Rank Fusion with the existing dense leg, self-hosted cross-encoder reranking — same mandatory `workspace_id` filter, same search route/contract | done |
| `050-vision-captioning` | Vision LLM captioning for extracted images at ingestion time, replacing OCR-only text as the primary embedded signal while keeping OCR for exact-string matches | done |
| `051-table-intelligence` | Durable raw table storage, LLM-generated table summaries as primary embedded text, column schema metadata, normalized `document_tables`/`table_cells` rows (RLS-protected), row-group chunking for large tables | done |
| `060-retrieval-evaluation` | Golden retrieval dataset (from `sample.pdf`'s own built-in eval section), eval CLI over `packages/retrieval`'s public functions, recall@k/precision@k/latency, comparable before/after reports (hybrid vs. dense-only) | done |
| `061-observability-tracing-metrics` | OpenTelemetry tracing (Jaeger) across auth/retrieval/ingestion, Prometheus + Grafana metrics, Sentry error tracking — all native/free, no generation-pipeline dependency | in-progress (Sentry live-verification deferred) |
| `070-api-hardening` | CORS policy, per-caller rate limiting, security response headers, and a read endpoint over the existing `audit_log` table — the baseline `apps/api` needs before real browser traffic | done |
| `071-search-frontend` | `apps/UI` React SPA (Vite): Keycloak login, workspace/member management, document upload + live ingestion status, content-type-aware search results — chat deferred pending a generation pipeline | in-progress (real-browser verification pending — no browser in this environment) |

Add a row here every time a new `specs/<NNN-slug>/` folder is created (`.claude/skills/spec/SKILL.md`
Stage 1). Status values: `draft` -> `approved` -> `in-progress` -> `done`.
