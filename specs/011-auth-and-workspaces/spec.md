# Spec: Auth and Workspaces

- **ID:** `011-auth-and-workspaces`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 2 — Metadata DB +
  Object Storage + Auth + Multi-Doc (this spec covers the auth/workspace half; DB/storage was
  `010-metadata-db-and-object-storage`)
- **Status:** approved
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-08-24

## Problem statement

`010-metadata-db-and-object-storage` shipped the `tenants`/`users`/`tenant_members`/
`workspaces`/`workspace_members` tables and Postgres Row-Level Security policies keyed on a
session GUC (`app.current_tenant_id`) — but nothing sets that GUC, and there is no way to
authenticate a caller, resolve who they are, or manage tenant/workspace membership at all.
`apps/api` is still empty scaffolding (`apps/api/{routers,deps,schemas}/.gitkeep`) — this
repo has never served an HTTP request. Per
[06-security-model.md](../architecture/06-security-model.md), production behavior requires
JWT verification on every request and RBAC resolved from Postgres membership tables, never
trusted from token claims alone. Every later phase (async ingestion job ownership, tenant
retrieval filtering, multi-doc UX) needs real identity and workspace context to attach work
to — none of that is possible yet.

## Goals

- Stand up the first working `apps/api` service (per
  [09-repo-and-module-structure.md](../architecture/09-repo-and-module-structure.md)),
  reachable over HTTP for the first time in this repo, plus `packages/auth` for the
  verification/RBAC logic it depends on.
- Every route except a health check requires a verified JWT (signature, expiry,
  issuer/audience) issued by a configured external IdP — no endpoint accepts unauthenticated
  requests.
- The caller's `(user, tenant, workspace)` context for a request is resolved from
  `tenant_members`/`workspace_members` in Postgres, never trusted from a `tenant_id` claim in
  the JWT — a request naming a tenant/workspace the caller doesn't belong to is rejected, not
  silently scoped to nothing.
- The resolved `tenant_id` is set as the `app.current_tenant_id` session GUC for the duration
  of each request's database session, so the Row-Level Security policies from
  `010-metadata-db-and-object-storage` take effect for the first time.
- RBAC: routes declare the minimum tenant role (owner/admin/member) or workspace role
  (owner/editor/viewer) they require; a shared guard rejects with 403 before business logic
  runs if the caller's resolved role doesn't meet it.
- An authenticated user can: create a tenant (becoming its owner), create workspaces within a
  tenant they administer, add/remove members (with a role) to a tenant or workspace they
  administer, and list the tenants/workspaces they belong to.
- A tenant admin can issue and revoke `api_keys` (per
  [02-data-model.md](../architecture/02-data-model.md)) for programmatic access — scoped,
  hashed at rest, usable as an alternative to a user JWT on the same auth middleware.
- Every security-relevant action this spec introduces (membership added/removed/role changed,
  api key created/revoked) writes an `audit_log` row.

## Non-goals

- No document/ingestion/job/chat/feedback endpoints or routers — this spec is auth and
  tenant/workspace administration only. Those routers land in
  `020-async-ingestion-pipeline` and later phases.
- No retrieval-time Qdrant filtering — that's Phase 4
  (`030-039`, `06-security-model.md` §4). Postgres RLS (from `010`) is the only enforcement
  mechanism exercised by this spec; Qdrant isn't touched.
- No `apps/UI` (public web frontend) or its login flow — this spec is API-only. A UI
  consuming this API is a separate future spec.
- No usage-quota enforcement or billing (`080-089`) — `usage_quotas` rows aren't written or
  read here.
- No self-service tenant deletion, workspace deletion, or membership self-removal — only
  creation and role/membership management by an admin/owner. Deletion flows are deferred to
  whichever spec first needs them (avoids speccing an irreversible operation nobody's asked
  for yet).
- No specific IdP product is chosen by this spec — see Open questions.

## User-facing behavior

No UI yet; the observable behavior is at the API-consumer level:

- A client with a valid JWT can call `apps/api` and receive responses scoped to their own
  tenant/workspace membership.
- A client with no JWT, an invalid/expired JWT, or a JWT for a tenant/workspace they don't
  belong to receives `401` (no/bad auth) or `403` (authenticated, but not authorized for this
  tenant/workspace/role) as appropriate — never a silently-empty success response.
- Creating a tenant makes the caller its owner. Creating a workspace requires tenant
  admin+. Adding a member to a tenant or workspace requires the corresponding admin/owner
  role. Issuing or revoking an API key requires tenant admin+.
- A `404` for "this resource doesn't exist" and a `404` for "this resource exists but you
  can't see it" are indistinguishable in the response body (per
  `06-security-model.md` §5) — no enumeration of other tenants' resource IDs via error
  messages.

## Acceptance criteria

- [ ] `apps/api` starts and serves a health-check endpoint that requires no authentication.
- [ ] Every non-health route rejects a request with no `Authorization` header, or an
      invalid/expired/wrong-issuer JWT, with `401`.
- [ ] A request with a valid JWT for a user who has no membership in the target
      tenant/workspace is rejected with `403`.
- [ ] After successful auth + scope resolution, `app.current_tenant_id` is set on that
      request's database session; an integration test with two tenants proves a scoped query
      (e.g. "list my workspaces") returns only the caller's tenant's rows, relying on the RLS
      policy from `010` actually being active.
- [ ] RBAC is enforced per role: a workspace route requiring `editor` rejects a `viewer`-role
      caller with `403`; a tenant route requiring `admin` rejects a `member`-role caller with
      `403`.
- [ ] An authenticated user can create a tenant and is automatically added to
      `tenant_members` as `owner`.
- [ ] A tenant `owner`/`admin` can create a workspace within their tenant.
- [ ] A workspace `owner` can add an existing user to that workspace with a specified role.
- [ ] A tenant `admin`+ can create an API key; the plaintext key is returned exactly once at
      creation and never again; a request authenticated with a since-revoked key is rejected.
- [ ] Membership changes (add/remove/role change) and API key create/revoke each write one
      `audit_log` row with the acting user, action, and affected resource.
- [ ] An authorization test suite directly asserts: user A's request for a
      tenant/workspace/resource user A cannot access returns `403`/`404`, never a
      filtered-but-200 response.
- [ ] `apps/api` never holds or forwards provider API keys (OpenAI/Qdrant/reranker) — this
      spec's routes don't need them and don't touch `packages/generation`/`packages/retrieval`.
- [ ] No changes to `packages/ingestion`/`packages/retrieval`/`packages/generation`/
      `packages/parsing`.

## Constraints

- Builds on the `packages/db` schema from `010-metadata-db-and-object-storage` as-is; any
  gap found must be fixed by updating `02-data-model.md` in the same session, not worked
  around silently.
- Must never trust a `tenant_id`/`workspace_id`/role claim embedded in a JWT — always
  re-derive current membership/role from `tenant_members`/`workspace_members` per request
  (`06-security-model.md` §2).
- Python 3.12, `uv`-managed, per `CLAUDE.md`. `packages/auth` wraps and re-raises failures as
  `DocumentPortalException`-style exceptions from `packages/exceptions`, matching `packages/db`
  and `packages/storage`.
- No provider API keys (OpenAI, Qdrant, reranker) touched by this spec.
- Local dev must remain runnable without Docker, consistent with how `010` was verified
  (native Postgres/MinIO) — whatever IdP approach is chosen must have a viable non-Docker
  local dev/test story (see Open questions).

## Open questions

- **Which IdP to standardize on.** `06-security-model.md` §2 explicitly defers this
  ("Keycloak self-hosted... or Auth0/Clerk managed... pick one per the deployment target").
  This materially changes local-dev complexity: Keycloak self-hosted needs another local
  service (and per this project's current no-Docker-locally preference, another native
  install); a managed IdP (Auth0/Clerk) avoids that locally but needs an external account and
  a way to mint test JWTs for automated tests without depending on a live third-party service
  per test run. Needs a decision before/at `plan.md`.
- **Is tenant creation self-service or admin-provisioned?** Neither the assignment nor the
  roadmap says. This spec defaults to self-service (any authenticated user can create a
  tenant and becomes its owner) since that's what a solo developer testing this locally
  needs, and it can be restricted later without a breaking schema change. Flagging in case
  that default is wrong for the intended deployment.
