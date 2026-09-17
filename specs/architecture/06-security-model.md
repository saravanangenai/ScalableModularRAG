# Security Model — AuthN, AuthZ, Tenant Isolation, Secrets, Audit

- **Status:** approved baseline

> ⚠️ **Single-tenant as-built — see [`specs/012-single-tenant-simplification`](../012-single-tenant-simplification/spec.md).**
> The tenant layer is removed. Authentication (§2, JWT verification, JIT provisioning) is
> unchanged. Authorization is **workspace RBAC only** — no tenant role ladder (§3). The
> mandatory retrieval-time filter (§4) is **implemented** (`packages/retrieval`, dense-only —
> `specs/030-workspace-rbac-filtering`) with `workspace_id` as its sole server-constructed
> dimension; hybrid search/reranking are still Phase 5. Postgres Row-Level Security (§5) is
> **implemented** as defense-in-depth for `documents`/`document_versions`/`ingestion_jobs`/
> `api_keys`/`audit_log` (migration `0002`, `specs/030-workspace-rbac-filtering`) —
> `workspaces`/`workspace_members` stay unprotected (role must be resolvable before the GUC
> exists) and `conversations`/`messages`/`message_feedback` stay unprotected (no route uses
> them yet). `audit_log` (§7) is workspace-scoped. Tenant-specific text below is marked
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
- **Browser client** (`apps/UI`, `071-search-frontend`): OIDC Authorization Code + PKCE
  against the same `mm-rag` Keycloak realm, through a dedicated **public** client
  (`mm-rag-ui` — `publicClient: true`, `standardFlowEnabled: true`,
  `directAccessGrantsEnabled: false`, mandatory `S256` PKCE, no client secret — public
  clients can't hold one; PKCE is what prevents authorization-code interception in its
  place). Distinct from the confidential `mm-rag-api` test client
  (`tests/integration/conftest.py`'s Resource Owner Password Credentials flow) and from
  `api_keys`'s service-to-service auth. `apps/api`'s JWT verification is unchanged and
  unaware of which client issued a token — it checks issuer/audience, not client identity,
  so a token from `mm-rag-ui` is verified exactly like any other.

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

**Authorization must be part of the retrieval query, not only hidden in the UI.** Implemented
in `specs/030-workspace-rbac-filtering` (`packages/retrieval`,
`POST /workspaces/{workspace_id}/search`) as dense-vector-only search; hybrid/rerank land in
Phase 5 (`04-retrieval-design.md`) on top of the same filter contract. Concretely:

1. The API resolves the authenticated user's accessible `workspace_id` (via the existing
   `require_workspace_role` guard, resolved from `workspace_members`) — never from
   client-supplied input. Finer-grained document ACLs within a workspace remain a possible
   future dimension; the current data model only has workspace-level membership.
2. `packages/retrieval::search` (`packages/retrieval/filters.py::build_workspace_filter`)
   receives that resolved `workspace_id` as a **server-constructed** Qdrant filter — the
   same `must=[FieldCondition(...)]` pattern `src/retriever.py::build_filter` used in the
   prototype, just with a `workspace_id` condition that's never optional and never
   client-editable (unlike a future `filename`/`content_types`/`page_number` filter, which
   would remain optional/client-chosen). (Deferred multi-tenant target would add a
   `tenant_id` condition alongside it.) The filter also unconditionally requires
   `is_current_version = true`, so a superseded document version never surfaces.
3. A request that omits a workspace scope is rejected at the routing layer (no route exists
   without a `workspace_id` path segment) — never defaulted to "search everything," the
   exact V1 failure mode this must not reproduce in production.
4. This is tested directly: `tests/integration/test_search_rbac.py` asserts that user A's
   query, run against a workspace user A cannot access, returns `403`/`404` with no
   workspace-B identifiers in the response body — not just "correct" results that happen to
   be filtered client-side.

## 5. Isolation strategy

- **Payload-based partitioning** in a shared Qdrant collection (assignment 3.4's explicit
  guidance — not a collection per user), with a `workspace_id` payload index for fast,
  mandatory filtering (`02-data-model.md` §0/§3).
- **Application-layer enforcement**: every Postgres query filters by `workspace_id` behind a
  `workspace_members` role check resolved server-side.
- **Defense in depth via Postgres Row-Level Security** (`02-data-model.md` §0/§2) —
  implemented in `specs/030-workspace-rbac-filtering` (migration `0002`). Policies on
  `documents`, `api_keys`, `audit_log` (direct `workspace_id` column) and
  `document_versions`, `ingestion_jobs` (joined via `document_id` — no direct column) key off
  an `app.current_workspace_id` session GUC, set by `apps/api/deps/rbac.py::require_workspace_role`
  after the caller's role is already authorized, and by the Celery worker
  (`packages/db/rls.py::set_workspace_scope_sync`) using the `workspace_id` the enqueuing
  request already resolved — the worker never goes through `apps/api`, so it has to set its
  own scope. `FORCE ROW LEVEL SECURITY` is load-bearing here: the single `postgres_user`
  configured in `packages/db/config.py` owns every table it migrated, and Postgres exempts
  table owners from RLS unless forced. `workspaces`/`workspace_members` are deliberately
  unprotected (the caller's role must be resolvable from `workspace_members` *before* the GUC
  can be set); `conversations`/`messages`/`message_feedback` are unprotected because no route
  reads or writes them yet — RLS for those is deferred to whichever spec first adds chat.
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
are queryable by that workspace's `owner` — implemented (`070-api-hardening`): `GET
/workspaces/{workspace_id}/audit-log`, paginated, `owner`-role-gated, same RLS policy as
every other protected table. (Deferred: per-tenant scoping and plan-tier retention.)

## 9. External-traffic hardening (070-api-hardening)

Once `apps/api` serves a real browser client (`071-search-frontend`), it needs baseline
protections a trusted-caller-only API didn't:

- **CORS**: `CORSMiddleware`, allow-list configured via `apps/api/config.py::
  Settings.cors_allowed_origins` (no wildcard `*` — exact origins only). CORS is a
  browser-enforced boundary, not a server-side authorization mechanism; it doesn't replace
  `require_workspace_role`, and non-browser callers (`curl`, `eval/`, `tests/integration`'s
  `ASGITransport`) are unaffected by it entirely.
- **Rate limiting**: a fixed-window counter in Redis (the same instance Celery already
  uses, a distinct `ratelimit:` key prefix — no new infrastructure), applied to `/search`
  and document upload (the two cost-bearing routes — every `/search` call triggers a real
  paid OpenAI embedding call plus a Qdrant query). Scoped per caller identity (JWT
  `user.id`, or the API key's `workspace_id`), so one caller hitting its limit cannot affect
  another's. Exceeding it returns `429` with a `Retry-After` header.
- **Security headers**: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`
  applied to every response via middleware — defense-in-depth against clickjacking/
  MIME-sniffing for a browser client, no interaction with the auth/isolation model.

None of the above changes `require_workspace_role`, JWT verification, or the RLS/workspace-
filter isolation model — they're additive policy layers around the existing auth path.

## 10. Related docs

- `02-data-model.md` — the tables this model depends on
- `04-retrieval-design.md` §6 — the filter contract this section constrains
- `07-evaluation-observability.md` — audit log doubles as an input to usage/observability
  dashboards
