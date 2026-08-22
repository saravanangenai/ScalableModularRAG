# Phased Roadmap

- **Status:** approved baseline
- **Process:** each phase below is implemented as one or more specs under `specs/<NNN-slug>/`
  via the workflow in `.claude/skills/spec/SKILL.md`. Spec IDs are pre-allocated in blocks of
  10 per phase so later insertions don't require renumbering.

## Why this order

The order follows the assignment's own recommended roadmap, with one adjustment: **object
storage/Postgres/async ingestion (assignment's Phase 3) is pulled forward to run alongside
multi-doc/auth (Phase 2)**, because auth and multi-tenancy are meaningless without a real
metadata database to hold users/workspaces/permissions in — building "auth" against local
files first would mean rebuilding it days later. Everything after that follows the
assignment order as-is: it's already sequenced so that each phase depends only on
infrastructure the previous phase established (retrieval quality work needs multi-tenant
filtering to exist first so it can be tested safely; evaluation needs a stable retrieval
pipeline to be worth measuring; the public API/frontend needs the backend to already be
service-shaped).

## Phases

| Phase | Spec block | What ships | Depends on | Why it's here and not later/earlier |
|---|---|---|---|---|
| **0 — Foundations** | `000-009` | This spec set, `.claude` workflow, repo scaffold (`09-repo-and-module-structure.md`), CI skeleton | — | Nothing else is reviewable without a place to put specs and a repo shape to implement into |
| **1 — Current V1** | *(baseline, already exists)* | Streamlit + local parsing/ingestion/dense retrieval/generation, single user | — | Starting point; not re-implemented, extended |
| **2 — Metadata DB + Object Storage + Auth + Multi-Doc** | `010-019` | PostgreSQL schema (`02-data-model.md`), S3/MinIO object storage, IdP-backed auth (`06-security-model.md` §2-3), multiple documents per authenticated user/workspace | Phase 0 | Everything downstream (async jobs, tenant filtering, quotas, audit) needs identity and a real database to exist first — doing this early avoids rebuilding "who owns this document" logic twice |
| **3 — Async Ingestion** | `020-029` | Job queue (Celery+Redis), parser workers, status states (`03-ingestion-workflow.md`) | Phase 2 (jobs need `ingestion_jobs` rows and object storage) | Blocking uploads is the most visible V1 limitation and the one most likely to break with real (large/many) documents; also unblocks scaling parsing independently of the API |
| **4 — Tenant/RBAC Filtering** | `030-039` | Mandatory retrieval-time filter (`06-security-model.md` §4), RBAC route guards, authorization test suite | Phase 2 (needs `workspace_members`), Phase 3 (needs ingestion writing tenant-scoped payload) | Retrieval quality work in the next phase must be built and tested against an already-isolated system — building hybrid search first and bolting isolation on after risks shipping a retrieval change that accidentally bypasses filters |
| **5 — Hybrid Retrieval + Reranking** | `040-049` | Dense+sparse+RRF+cross-encoder rerank (`04-retrieval-design.md`) | Phase 4 (filters must wrap the new pipeline from day one, not be retrofitted) | Directly addresses the weakest part of V1 (dense-only search); needs isolation in place first per above |
| **6 — Better Multimodal Retrieval** | `050-059` | Vision captioning for images, table intelligence (summary/schema/normalized rows) (`05-multimodal-strategy.md`) | Phase 5 (captions/summaries feed the same hybrid pipeline) | Multimodal quality is currently OCR/markdown-dependent (the assignment's stated gap); doing this after hybrid retrieval exists means captions/summaries immediately benefit from sparse+rerank rather than only dense search |
| **7 — Evaluation + Observability** | `060-069` | Golden eval dataset, eval CLI, OpenTelemetry tracing, Prometheus/Grafana, Sentry, feedback loop (`07-evaluation-observability.md`) | Phases 5-6 (there needs to be a retrieval/multimodal pipeline worth measuring) | Could theoretically start earlier, but a golden dataset built against V1 dense-only retrieval would need rewriting once hybrid+multimodal lands; sequencing after keeps the eval baseline meaningful for future comparisons |
| **8 — Production API + Frontend** | `070-079` | `apps/web` (Next.js) public product UI, `apps/api` hardened for external traffic, `apps/streamlit-admin` fully migrated off direct `src/*` imports | Phases 2-7 (the API surface being exposed publicly must already be authenticated, isolated, and observable) | Exposing a polished public frontend before auth/isolation/observability exist would mean shipping a nicer UI on top of an unsafe backend |
| **9 — Enterprise Integrations + Billing** | `080-089` | Connectors (Drive/SharePoint/S3), `usage_quotas` enforcement, billing/subscription controls, audit log UI | Phase 8 | Enterprise features are additive surface area on top of an already-multi-tenant, already-observable product — building them earlier has nothing stable to attach to |

## What's built first, concretely

Given the above, the first three specs to write (in order) are:

1. `010-metadata-db-and-object-storage` — Postgres schema + migrations, S3/MinIO wiring, no
   UI changes yet.
2. `011-auth-and-workspaces` — IdP integration, `tenant_members`/`workspace_members`, API
   auth middleware, still single-document-at-a-time UX is fine at this point.
3. `020-async-ingestion-pipeline` — Celery/Redis, parser workers, job status endpoints,
   wiring `src/parsing.py`/`src/ingestion.py` logic into `packages/ingestion` behind the
   queue instead of the Streamlit request thread.

Each gets its own `spec.md` -> `plan.md` -> `tasks.md` via `.claude/skills/spec/SKILL.md`
before any code is written.

## Related docs

- `01-system-architecture.md` — the end state every phase converges toward
- `09-repo-and-module-structure.md` — where Phase 0's scaffold lives
- `specs/README.md` — live status tracker per spec, updated as work progresses
