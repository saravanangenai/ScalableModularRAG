# Plan: Search Frontend (apps/UI)

- **Spec:** [spec.md](spec.md) (approved 2026-09-16)
- **Status:** approved (approved 2026-09-16, including the new Keycloak client and OIDC
  flow per `CLAUDE.md`'s auth-adjacent-plan ground rule)

## Summary

A Vite + React + TypeScript SPA under `apps/UI`, authenticating via OIDC Authorization Code +
PKCE against the **existing** `mm-rag` Keycloak realm through a **new public client**
(`mm-rag-ui`) — `scripts/setup_keycloak_dev.py` (the same Admin-REST-API bootstrap script
`010`/`011` already use for the confidential test client) gets a new `ensure_spa_client()`
function alongside the existing `ensure_client()`. The app talks to `apps/api` exclusively
via a thin typed fetch wrapper, uses TanStack Query for data-fetching/caching/polling, and
Mantine for UI components (forms, tables, notifications) to avoid spending this increment on
custom component work, per spec's non-goal on visual polish.

## Architecture doc deltas

| Doc | Change |
|---|---|
| `06-security-model.md` | §2 (Authentication): note the browser flow — OIDC Authorization Code + PKCE via a public Keycloak client (`mm-rag-ui`), distinct from the existing confidential test client and from `api_keys`'s service-to-service auth. No backend verification logic changes: `apps/api` still verifies the same realm's JWTs via `packages/auth/jwt.py`, unaware of which client issued them. |
| `09-repo-and-module-structure.md` | `apps/UI/` gets a concrete internal structure (below) replacing the placeholder comment. |

## Component/module ownership

**Keycloak (realm config, not app code):**
- **`scripts/setup_keycloak_dev.py::ensure_spa_client()`** (new function, alongside the
  existing `ensure_client()`) — creates/confirms a **public** client `mm-rag-ui`:
  `publicClient: true`, `standardFlowEnabled: true` (Authorization Code), `directAccessGrantsEnabled:
  false` (no password grant for this client — browser-only), `pkceCodeChallengeMethod: "S256"`
  (required), `redirectUris: ["http://localhost:5173/*"]` (Vite dev server; production origin
  added when `071` is actually deployed, not yet decided), `webOrigins: ["http://localhost:5173"]`
  (so Keycloak's own token/userinfo endpoints accept the browser's CORS preflight). No client
  secret (public clients don't get one — PKCE replaces the secret's role). Idempotent, same
  "already exists, skip" pattern as `ensure_client()`.

**`apps/UI/` (new app):**
```
apps/UI/
├── index.html
├── vite.config.ts
├── package.json
├── src/
│   ├── main.tsx                 # mounts App, wraps in AuthProvider + QueryClientProvider + MantineProvider
│   ├── App.tsx                  # React Router routes
│   ├── auth/
│   │   ├── AuthProvider.tsx      # react-oidc-context config (authority, client_id, PKCE)
│   │   └── RequireAuth.tsx       # route guard — redirects to login if unauthenticated
│   ├── api/
│   │   ├── client.ts             # thin fetch wrapper: injects Bearer token, base URL, typed responses
│   │   ├── workspaces.ts         # list/create workspace, list/add/update/remove member
│   │   ├── documents.ts          # upload, list, get, list versions
│   │   ├── jobs.ts                # get job status
│   │   └── search.ts             # POST search
│   ├── pages/
│   │   ├── LoginCallback.tsx      # OIDC redirect target
│   │   ├── WorkspaceListPage.tsx
│   │   ├── WorkspacePage.tsx      # tabs: Documents, Members, Search
│   │   ├── DocumentsTab.tsx       # upload + list + per-doc job status (polled)
│   │   ├── MembersTab.tsx         # list/add/update-role/remove, owner-only actions gated by role from API responses
│   │   └── SearchTab.tsx          # query box + content-type-aware result rendering
│   └── components/
│       ├── ResultCard.tsx         # renders one SearchResultOut: text / table / image variants
│       └── JobStatusBadge.tsx
├── .env.development               # VITE_API_BASE_URL, VITE_KEYCLOAK_URL, VITE_KEYCLOAK_REALM, VITE_KEYCLOAK_CLIENT_ID
└── vitest config + component tests (co-located *.test.tsx)
```

- **`auth/AuthProvider.tsx`** — wraps `react-oidc-context`'s `AuthProvider` with this
  project's settings (`authority: {VITE_KEYCLOAK_URL}/realms/mm-rag`, `client_id:
  mm-rag-ui`, `redirect_uri`, `response_type: "code"`, PKCE on by default in
  `oidc-client-ts`). Exposes the current user/token via the library's `useAuth()` hook —
  no custom token-storage/refresh code written by this app (the library handles silent
  renewal).
- **`api/client.ts`** — every call attaches `Authorization: Bearer {access_token}` from
  `useAuth()`'s context; centralizes error handling (401 -> redirect to login, 403/404 ->
  surfaced to the calling page, 429 -> shows the `070`-added rate-limit message with
  `Retry-After` if present).
- **`pages/DocumentsTab.tsx`** — after upload, polls `GET /workspaces/{id}/jobs/{job_id}`
  via a TanStack Query hook with `refetchInterval` that stops once status is terminal
  (`ready`/`failed`) — this is the "watch status update without manually refreshing" goal.
- **`components/ResultCard.tsx`** — switches on `SearchResultOut.content_type`:
  `page_text_plus_ocr` renders `text` as a snippet; `table` renders `text` (already
  markdown-formatted per `051`) through a markdown-table renderer; `image` shows
  `filename`/`page_number`/`image_index` plus the `vision_caption` text embedded in `text`
  (no new image-serving endpoint in this increment — `image_path` is an internal storage
  key, not a public URL; serving the actual image bytes to the browser is out of scope here,
  tracked as a follow-up once there's a real need for it beyond this caption-based
  rendering).

## Data model changes

None in Postgres/Qdrant. The only new persistent state is the Keycloak realm's new client
definition (`mm-rag-ui`), managed the same way the existing test client already is.

## API contract

**Deviation, found during Group 3 implementation:** `apps/api` had no way to *list* a
workspace's members — only `POST`/`PATCH`/`DELETE` on `/workspaces/{id}/members` existed,
each acting on a `user_id` the caller already has to know. Spec's Goals/User-facing behavior
explicitly commit to "view and manage workspace members," and the Members tab cannot offer
role-change/remove actions on members it has no way to discover — this is small, additive,
and read-only, so implemented rather than silently descoping "view" from the spec:

- New: `GET /workspaces/{workspace_id}/members` — `require_workspace_role("viewer")`
  (matching every other read route on a workspace; seeing co-members isn't privileged, unlike
  the owner-only write actions), returns `list[MemberOut]` (`user_id`, `email`,
  `display_name`, `role`), joined against `User` for a usable display name/email rather than
  a bare UUID.

Otherwise no changes to `apps/api`'s contract: this app is a pure consumer of the existing
routes (`workspaces.py`, `documents.py`, `jobs.py`, `search.py`) plus whatever
`070-api-hardening` adds (CORS headers it depends on, `429`s it must handle, the new
audit-log route it doesn't use yet — out of scope per spec's non-goals). If `070` lands
first, this app's local-dev CORS origin (`http://localhost:5173`) must be in `070`'s
`cors_allowed_origins` default — cross-checked against `070-api-hardening/plan.md`'s stated
default, which already matches.

## Retrieval / ingestion impact

None — this app calls existing endpoints unchanged.

## Security / tenancy impact

- **New Keycloak client, not new backend auth logic.** `apps/api`'s JWT verification
  (`packages/auth/jwt.py::verify_token`) checks issuer + audience, not which client
  requested the token — a token from `mm-rag-ui` is verified identically to one from the
  existing test client, since both come from the same realm/audience. No change to
  `packages/auth` code.
- **Public client, no secret.** `mm-rag-ui` cannot authenticate itself with a client secret
  (public clients don't have one) — PKCE (mandatory `S256` challenge) is what prevents
  authorization-code interception, the standard mitigation for exactly this client type.
  `directAccessGrantsEnabled: false` on this client means it cannot use Resource Owner
  Password Credentials even if someone tried — only the real browser-redirect flow works.
- **No provider secrets in the browser.** OpenAI/Qdrant/reranker keys are never referenced
  anywhere in `apps/UI` — every provider call already happens server-side
  (`apps/api`/`workers`), unchanged by this spec.
- **Client-side role display is UX only.** `MembersTab.tsx` shows/hides owner-only actions
  based on the role the API already returned for the current user, purely to avoid showing a
  button that would 403 — the actual enforcement stays server-side in
  `require_workspace_role`, exactly as spec's Constraints require.

## Rollout

Big-bang, no flag:
- New app, zero existing code touched beyond `scripts/setup_keycloak_dev.py` (additive
  function) and the architecture docs above.
- Local dev: `cd apps/UI && npm install && npm run dev` (Vite dev server on `:5173`),
  alongside the existing `uv run uvicorn apps.api.main:app --reload` and Keycloak.
- Revert path: delete `apps/UI/`'s contents and the new Keycloak client; nothing else
  depends on either.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `react-oidc-context`/`oidc-client-ts` version drift or a Keycloak-specific OIDC quirk (e.g. token refresh edge cases) not surfacing until real browser testing | Medium — this is the first time this repo does browser-based OIDC | Medium — auth is the app's entry point; a broken flow blocks everything else | Live-verify the full login -> token -> API call -> silent-refresh cycle in a real browser against the real Keycloak realm before considering this spec done, not just unit-testing the wrapper components |
| Vite dev server origin (`:5173`) drifts from whatever `070-api-hardening`'s CORS default actually ships with, if the two specs are implemented out of order or independently adjusted | Low | Low — a config mismatch caught immediately by a failed preflight in dev | Confirmed cross-referenced above; re-verify at implementation time regardless |
| Mantine's bundle size / opinionated styling requires more override work than expected for the specific screens here | Low | Low — cosmetic, not functional | Accepted; `070`'s sibling framing already de-scopes visual polish, so this is a non-blocking risk |

## Alternatives considered

- **`keycloak-js`** (Keycloak's own official JS adapter) instead of `react-oidc-context` —
  considered, rejected: `keycloak-js` couples the app tightly to Keycloak-specific APIs and
  has had periods of reduced maintenance attention; `react-oidc-context` (wrapping the
  actively-maintained, OIDC-certified `oidc-client-ts`) works against any standards-compliant
  OIDC provider, and Keycloak is one via its standard `/realms/{realm}/.well-known/
  openid-configuration` discovery document — no Keycloak-specific code needed either way, so
  the standards-based library is the safer long-term bet with no real cost today.
- **Hand-rolled `fetch`-based data loading** instead of TanStack Query — rejected: the
  "watch job status without manually refreshing" goal needs polling-with-cancellation, which
  TanStack Query provides out of the box (`refetchInterval`, automatic cleanup on unmount);
  hand-rolling this is exactly the kind of infrastructure code this spec shouldn't spend
  effort re-deriving.
- **shadcn/ui** instead of Mantine — considered: shadcn/ui's copy-paste-component model gives
  more long-term customization control, but requires more upfront assembly (Tailwind config,
  per-component copy-in) for a spec whose explicit non-goal is visual polish; Mantine's
  batteries-included provider + component set gets working screens faster, which is the
  actual priority here. Revisit if a future spec wants deeper visual customization.
- **Serving actual image bytes to the browser** (a new `apps/api` route streaming from object
  storage) for image search results — considered, deferred: `050`'s vision-caption text
  already gives a meaningful result without it, and adding an image-serving route/CDN
  question is more surface area than this increment needs; tracked as a natural follow-up,
  not silently dropped.
