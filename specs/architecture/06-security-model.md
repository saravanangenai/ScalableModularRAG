# Security Model — AuthN, AuthZ, Tenant Isolation, Secrets, Audit

- **Status:** approved baseline

> ⚠️ **Single-tenant as-built — see [`specs/012-single-tenant-simplification`](../012-single-tenant-simplification/spec.md).**
> The tenant layer is removed. Authentication (§2, JWT verification, JIT provisioning) is
> unchanged. Authorization is **workspace RBAC only** — no tenant role ladder (§3). The
> mandatory retrieval-time filter (§4) uses `workspace_id` as its sole server-constructed
> dimension. Postgres Row-Level Security (§5) is **not implemented** — application-layer
> workspace filtering is the enforcement, with RLS + the Qdrant retrieval filter deferred to
> Phase 4. `audit_log` (§7) is workspace-scoped. Tenant-specific text below is marked
> ⚠️ DEFERRED (roadmap Phase 10).

## 1. Current state (V1)

There is no authentication, no authorization, and no tenant concept — `ui/app.py` is a
single-user local Streamlit app. Secrets (`OPENAI_API_KEY`, `QDRANT_API_KEY`, etc.) live in
`.env`, which is correctly gitignored and not tracked (verified). The only "isolation" today
is the optional `filename`/`document_id` filter a user can toggle in the sidebar
(`current_pdf_only` in `ui/app.py`) — this is a UX convenience, not a security boundary; any
query without that filter searches the entire collection.

## 2. Authentication

- Identity provider: **Keycloak, self-hosted** (decided in
  `specs/011-auth-and-workspaces/plan.md`, over managed alternatives like Auth0/Clerk) — full
  local-dev control, no external account/cost, and works fully offline, consistent with this
  project's Docker-free local-dev direction. The API never handles raw passwords; Keycloak
  issues JWTs via its own token endpoint.
- `apps/api` verifies JWTs on every request (signature, expiry, issuer/audience) via a
  standard middleware; it does not mint its own session tokens.
- JWT claims carry `sub` (maps to `users.auth_provider_subject`), `tenant_id` is **not**
  trusted from the token if a user can belong to multiple tenants — instead the client
  specifies which tenant/workspace context it's operating in per request (e.g. a header or
  path segment), and the API validates that `(user, tenant)` pair against
  `tenant_members`/`workspace_members` before proceeding. This avoids the classic mistake of
  trusting a tenant_id claim that was valid at token-issue time but the user has since been
  removed from.
- `api_keys` (see `02-data-model.md`) provide programmatic/API access (assignment's
  "Public/API access") with scoped permissions, hashed at rest, revocable.
- Streamlit admin app authenticates the same way (service account or admin-role user JWT) —
  it is not exempt from auth just because it's "internal."

## 3. Authorization

RBAC, backed by `02-data-model.md`:

- **Workspace role** (`workspace_members.role`: owner/editor/viewer) — controls per-workspace
  actions (upload documents = editor+, delete documents = owner, ask questions = viewer+).
  Any authenticated user can create a workspace and becomes its `owner`.
- ⚠️ DEFERRED — **Tenant role** (`tenant_members.role`: owner/admin/member) — would control
  tenant-wide actions (billing, inviting members, creating workspaces). Removed by `012`.

Every API route declares the minimum role it requires; a shared dependency
(`require_role(workspace_role="viewer")`-style guard) resolves the caller's role for the
target workspace from `workspace_members` and rejects with 403 before any business logic
runs. This is the same pattern as any standard RBAC middleware — the point worth stating
explicitly is *where* it's enforced next.

## 4. Authorization at retrieval time (assignment 3.5 — the part that's easy to get wrong)

**Authorization must be part of the retrieval query, not only hidden in the UI.** Concretely:

1. The API resolves the authenticated user's accessible `workspace_id`s (and, within a
   workspace, any finer-grained document ACL) from Postgres — never from client-supplied
   input.
2. The Retrieval Service (`04-retrieval-design.md`) receives that resolved
   `workspace_id`/ACL set as a **server-constructed** Qdrant filter, applied to
   both the dense and sparse legs before fusion — the same `must=[FieldCondition(...)]`
   pattern `src/retriever.py::build_filter` already uses, just with workspace/ACL
   conditions that are never optional and never client-editable (unlike today's
   `filename`/`content_types`/`page_number` filters, which remain optional/client-chosen).
   (Deferred multi-tenant target would add a `tenant_id` condition alongside `workspace_id`.)
3. A request that omits a workspace scope is rejected, not defaulted to "search everything" —
   the current V1 default behavior (search the whole collection unless a filter is manually
   set) is the exact failure mode this must not reproduce in production.
4. This is tested directly: an authorization test suite asserts that user A's query, run
   against a workspace user A cannot access, returns zero results and a 403/404 at the API
   layer — not just "correct" results that happen to be filtered client-side.

## 5. Isolation strategy

- **Payload-based partitioning** in a shared Qdrant collection (assignment 3.4's explicit
  guidance — not a collection per user), with a `workspace_id` payload index for fast,
  mandatory filtering (`02-data-model.md` §0/§3).
- **Application-layer enforcement**: every Postgres query filters by `workspace_id` behind a
  `workspace_members` role check resolved server-side.
- ⚠️ DEFERRED — **Defense in depth via Postgres Row-Level Security** (`02-data-model.md` §2).
  Removed with the tenant GUC it depended on in `012`. Phase 4 owns re-adding workspace-scoped
  RLS and the mandatory Qdrant retrieval filter together, with the retrieval-bypass threat
  model in focus.
- **No cross-workspace identifiers leak in error messages** — a 404 for "document doesn't
  exist" and a 404 for "document exists but you can't see it" must be indistinguishable, so
  probing IDs can't be used to enumerate other workspaces' data.

## 6. Secrets management

- Local dev: `.env`, gitignored (current state — correct, keep it).
- Deployed environments: a managed secrets store (AWS Secrets Manager, GCP Secret Manager, or
  Vault), injected as environment variables at deploy time — `.env` files never ship to any
  non-local environment.
- Provider API keys (OpenAI, Qdrant, reranker) are held by the backend services only; the
  Web UI and Streamlit admin never receive them — all LLM/embedding calls proxy through
  `apps/api`/`packages/*`, matching how `src/generation.py`/`src/ingestion.py` already
  centralize those calls (they just need to stay server-side once a public frontend exists).
- Rotation: API keys stored in `api_keys` are hashed (never reversible), and provider secrets
  are rotated via the secrets manager without a code deploy.

## 7. Auditability

Every security-relevant action writes an `audit_log` row (`02-data-model.md`): document
upload/delete, workspace membership changes, role changes, API key creation/revocation, and
(configurable, since it's high-volume) chat queries. Audit log is append-only from the
application's perspective (no update/delete API); rows carry a nullable `workspace_id` and
are queryable by that workspace's `owner`. (Deferred: per-tenant scoping and plan-tier
retention.)

## 8. Related docs

- `02-data-model.md` — the tables this model depends on
- `04-retrieval-design.md` §6 — the filter contract this section constrains
- `07-evaluation-observability.md` — audit log doubles as an input to usage/observability
  dashboards
