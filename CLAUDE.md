# MM-RAG Platform (modular monorepo)

Target modular monorepo for a multimodal RAG platform over PDFs (text, OCR, tables,
images), built multi-tenant and production-grade from the start. Full design is in
`specs/` — this file is the short orientation, not a duplicate of it.

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

Note: `01-system-architecture.md` currently describes the web UI as Next.js under
`apps/web`, while `09-repo-and-module-structure.md` names it Vue.js under `apps/UI`. This
repo is scaffolded using the folder name from `09` (`apps/UI`); reconcile the framework/name
mismatch between the two docs before that app is actually built.

## Current state

Nothing is implemented yet. The directories below exist only as empty scaffolding
(`.gitkeep` placeholders) mirroring the target layout, waiting on their first approved spec:

```
apps/api/{routers,deps,schemas}/
apps/UI/
apps/streamlit-admin/
packages/{parsing,ingestion,retrieval,generation,db,storage,auth,observability,exceptions}/
workers/
eval/{datasets,reports}/
infra/
prompt_library/
tests/{unit,integration}/
```

Do not assume any of these packages/apps has real code, an API contract, or a schema until
a spec under `specs/<NNN-slug>/` says so and it's been implemented. Check the actual
directory contents, not this list, before relying on something existing.

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
- Multi-tenant/auth/retrieval-filter changes always get a `plan.md`, even when they look
  small — see `.claude/skills/spec/SKILL.md` ground rules.
