# Security Model — AuthN, AuthZ, Tenant Isolation, Secrets, Audit

- **Status:** approved baseline

## 1. Current state (V1)

There is no authentication, no authorization, and no tenant concept — `ui/app.py` is a
single-user local Streamlit app. Secrets (`OPENAI_API_KEY`, `QDRANT_API_KEY`, etc.) live in
`.env`, which is correctly gitignored and not tracked (verified). The only "isolation" today
is the optional `filename`/`document_id` filter a user can toggle in the sidebar
(`current_pdf_only` in `ui/app.py`) — this is a UX convenience, not a security boundary; any
query without that filter searches the entire collection.

## 2. Authentication

- Identity provider: an external IdP issuing JWTs — Keycloak (self-hosted, enterprise
  control) or Auth0/Clerk (managed, faster to stand up). Pick one per the deployment target;
  either way the API never handles raw passwords.
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

RBAC at two levels, both backed by `02-data-model.md`:

- **Tenant role** (`tenant_members.role`: owner/admin/member) — controls tenant-wide actions
  (billing, inviting members, creating workspaces).
- **Workspace role** (`workspace_members.role`: owner/editor/viewer) — controls per-workspace
  actions (upload documents = editor+, delete documents = owner, ask questions = viewer+).

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
   `tenant_id`/`workspace_id`/ACL set as a **server-constructed** Qdrant filter, applied to
   both the dense and sparse legs before fusion — the same `must=[FieldCondition(...)]`
   pattern `src/retriever.py::build_filter` already uses, just with tenant/workspace/ACL
   conditions that are never optional and never client-editable (unlike today's
   `filename`/`content_types`/`page_number` filters, which remain optional/client-chosen).
3. A request that omits a workspace scope is rejected, not defaulted to "search everything" —
   the current V1 default behavior (search the whole collection unless a filter is manually
   set) is the exact failure mode this must not reproduce in production.
4. This is tested directly: an authorization test suite asserts that user A's query, run
   against a workspace user A cannot access, returns zero results and a 403/404 at the API
   layer — not just "correct" results that happen to be filtered client-side.

## 5. Tenant isolation strategy

- **Payload-based partitioning** in a shared Qdrant collection (assignment 3.4's explicit
  guidance — not a collection per user), with `tenant_id`/`workspace_id` payload indexes for
  fast, mandatory filtering (`02-data-model.md` §3).
- **Defense in depth**: Postgres Row-Level Security policies (`02-data-model.md` §2) as a
  second, independent enforcement layer for anything queried directly from Postgres
  (conversations, documents, audit log), so a bug in application-layer filtering isn't the
  only thing standing between tenants.
- **No cross-tenant identifiers leak in error messages** — a 404 for "document doesn't exist"
  and a 404 for "document exists but you can't see it" must be indistinguishable, so probing
  IDs can't be used to enumerate other tenants' data.

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
application's perspective (no update/delete API), queryable by tenant admins for their own
tenant only, and retained per the tenant's plan tier.

## 8. Related docs

- `02-data-model.md` — the tables this model depends on
- `04-retrieval-design.md` §6 — the filter contract this section constrains
- `07-evaluation-observability.md` — audit log doubles as an input to usage/observability
  dashboards
