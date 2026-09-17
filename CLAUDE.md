# MM-RAG Platform (modular monorepo)

Target modular monorepo for a multimodal RAG platform over PDFs (text, OCR, tables,
images), built production-grade from the start. Full design is in `specs/` — this file is
the short orientation, not a duplicate of it.

**Tenancy:** `specs/012-single-tenant-simplification` removed the tenant layer for
assignment scope — the platform is **single-tenant as-built**: IdP login + workspace
owner/editor/viewer RBAC, no `tenants` tables, no `tenant_id` columns, no Row-Level
Security. Multi-tenancy stays the documented long-term target (roadmap Phase 10). The
architecture docs keep the multi-tenant design, marked ⚠️ DEFERRED.

The original single-process prototype (Streamlit UI calling a `src/*` pipeline directly,
no API, no auth, no multi-tenancy) lives in a separate sibling repo. Nothing has been
ported into this repo yet — see `specs/architecture/09-repo-and-module-structure.md` §3
("Mapping from the current repo") for exactly what moves where and in which phase.

## Where things are

- **Design/architecture:** `specs/architecture/` — read `01-system-architecture.md` first.
  These are living docs; keep them in sync with reality as specs implement them.
- **Roadmap:** `specs/architecture/08-roadmap.md` — what's built, in what order, and why.
- **Per-feature specs:** `specs/<NNN-slug>/{spec,plan,tasks}.md`, index in `specs/README.md`.
- **This repo's layout:** `specs/architecture/09-repo-and-module-structure.md` (`apps/api`,
  `apps/UI`, `apps/streamlit-admin`, `packages/*`) is the target this repo is scaffolded
  against — see below for what's a stub vs. what's implemented.

The web UI (`apps/UI`) is a **React SPA built with Vite** (React Router for routing, static
build output only — no Node server needed at runtime, calls `apps/api` for everything). This
was an open mismatch between `01-system-architecture.md` (said Next.js) and
`09-repo-and-module-structure.md` (said Vue.js); resolved when `070`'s spec work started —
both docs now say React/Vite consistently.

## Current state

Specs `010` through `061` are implemented (see `specs/README.md` for the live per-spec
status table — check it, not this paragraph, for what's actually done vs. in-progress).
Roughly: Postgres schema + migrations, S3/MinIO storage, Keycloak-backed auth, workspace
RBAC + Postgres RLS, async Celery ingestion (parsing/OCR/tables/images/vision captioning/
table intelligence), hybrid dense+sparse+RRF+rerank retrieval, a retrieval-quality eval CLI
(`eval/`), and OpenTelemetry tracing + Prometheus/Grafana metrics (Sentry wired but not
live-verified — no account provisioned yet) are all built and live-verified against a real
local stack (native Postgres/Keycloak/MinIO/Qdrant Cloud/Redis/Jaeger/Prometheus/Grafana,
`--pool=solo` Celery worker on Windows).

Still empty scaffolding (`.gitkeep` only, nothing built yet): `apps/UI/`,
`apps/streamlit-admin/`, `packages/generation/`, `prompt_library/` — these map to later
roadmap phases (generation/chat doesn't exist yet, which is why eval is retrieval-only and
Sentry/observability skip anything answer-quality-related).

Do not assume any package/app has real code, an API contract, or a schema beyond what
`specs/README.md` marks done — check actual directory contents and that table, not this
paragraph, before relying on something existing.

## How work happens here — spec-driven, always

**No implementation work starts without an approved spec.** Use the `spec` skill
(`.claude/skills/spec/SKILL.md`) for anything beyond a trivial fix: it drives
spec.md -> plan.md -> tasks.md under `specs/<NNN-slug>/`, with an approval checkpoint after
the spec and (for anything touching auth/tenancy/schema) after the plan. If a request doesn't
map to an existing roadmap phase, that's fine — it still goes through the same workflow as a
new spec folder.

Trivial fixes (typo, obvious bug with no design decision) don't need the full workflow — use
judgment, but default to spec-driven for anything that changes an API contract, the data
model, retrieval behavior, or security/tenancy.

## Conventions

- Python 3.12, managed with `uv`.
- Structured logging via `structlog`, in `packages/observability/` once built — log events
  as `snake_case_event_name` with keyword fields.
- Exceptions: wrap and re-raise as a `DocumentPortalException`-style exception at module
  boundaries (see the prototype repo's `exception/custom_exception.py` for the pattern this
  follows), landing in `packages/exceptions/`.
- Secrets live in `.env` (gitignored) locally; never hold provider API keys (OpenAI, Qdrant,
  reranker) in `apps/UI` or `apps/streamlit-admin` — see `specs/architecture/06-security-model.md` §6.
- Auth/tenancy/retrieval-filter changes always get a `plan.md`, even when they look
  small — see `.claude/skills/spec/SKILL.md` ground rules.
