# Spec: Search Frontend (apps/UI)

- **ID:** `071-search-frontend`
- **Roadmap phase:** [08-roadmap.md](../architecture/08-roadmap.md) Phase 8 — Production API
  + Frontend (`070-079`), the "`apps/UI` public product UI" half —
  [`01-system-architecture.md`](../architecture/01-system-architecture.md) §3,
  [`09-repo-and-module-structure.md`](../architecture/09-repo-and-module-structure.md).
  Sibling to `070-api-hardening` (CORS/rate-limiting/security headers this app's browser
  traffic depends on) — split out because this is a new app surface with its own
  (browser-auth-flow) design questions, while `070` is backend-only; they don't share code.
- **Status:** in-progress — code complete, typechecked, and server-side pieces
  integration-tested; real-browser end-to-end verification (login flow, live polling,
  visual rendering, sign-out) needs a human, since no browser is available in this
  environment (see Acceptance criteria)
- **Owner:** Saravanan Shanmugam
- **Date:** 2026-09-16

## Problem statement

Every capability this platform has built so far (`010` through `061`) is only reachable via
`curl`, pytest, or the `eval/` CLI — there is no UI a real user could open in a browser to log
in, create a workspace, upload a document, and search it. `apps/UI` exists only as empty
scaffolding (`.gitkeep`). This is the first spec that gives the platform an actual product
surface, per the assignment's "public product UI" requirement (3.1) and
`01-system-architecture.md`'s Web UI component (now React SPA via Vite — the
Next.js/Vue.js mismatch between that doc and `09-repo-and-module-structure.md` is resolved
as part of this spec's own planning, both now say React/Vite consistently; see `CLAUDE.md`).

`packages/generation` is still empty scaffolding — there is no chat/answer-synthesis pipeline
in this repo yet. `01-system-architecture.md`'s Web UI description ("workspaces, chat,
source/page preview, sharing, feedback") is the long-run target; this spec, like `060`'s
retrieval-only eval scoping before it, ships what's actually buildable against the real
backend today: workspace management, document upload/status, and a **search results**
experience (query in, ranked results with content-type-aware rendering out) — not a chat
interface. Chat is a follow-up spec once a generation pipeline exists.

## Goals

- A React SPA (Vite build, static output, no Node server at runtime) under `apps/UI` that
  calls `apps/api` exclusively — never Qdrant/Postgres directly, never holds a provider API
  key (`06-security-model.md` §6, `CLAUDE.md`'s convention).
- Browser-based login against the real Keycloak realm this platform already uses
  (`011-auth-and-workspaces`), landing the user in an authenticated session without ever
  handling their password in this app's own code.
- Workspace management: list the caller's workspaces, create one, view/manage members and
  their role (owner/editor/viewer) — covering the existing `workspaces.py` route surface.
- Document management: upload a PDF, see it and its ingestion job's live status (queued ->
  parsing -> chunking -> embedding -> indexing -> ready/failed, per
  `03-ingestion-workflow.md`), list previously uploaded documents.
- Search: submit a query against a workspace, see ranked results with the fields
  `SearchResultOut` already returns (filename, page number, content type, score, text/table/
  image reference) rendered appropriately per content type (`05-multimodal-strategy.md`) —
  a text snippet, a rendered table, or a reference to the source image.
- Sensible empty/loading/error states for every screen above (no upload yet, job still
  processing, search with no hits, an API error) — not just the happy path.

## Non-goals

- **Not** a chat/conversational interface, message history, or feedback (thumbs up/down) —
  all require `packages/generation`, which doesn't exist. Deferred to a follow-up spec once a
  generation pipeline lands; this spec's screens should not assume chat is coming imminently
  in a way that complicates today's simpler search-results UI.
- **Not** `apps/streamlit-admin` — separate, internal-tool scope; not started in this repo yet
  (nothing exists to migrate from), and not needed for the public product surface this spec
  targets.
- **Not** API-key management UI — `api_keys.py`'s routes exist for programmatic/service
  access, not something an end user manages through this product UI in the first increment.
- **Not** billing/quota UI, connector setup (Drive/SharePoint) — Phase 9 scope, and the
  underlying tables/routes don't exist yet.
- **Not** a design system or visual polish pass beyond "usable and coherent" — functional
  correctness and real-data wiring are this spec's bar, not pixel-perfect UI.
- **Not** CORS/rate-limiting on the API side this app depends on — that's `070-api-hardening`,
  sequenced so this app has something safe to call.

## User-facing behavior

- Visiting the app while logged out redirects to Keycloak's login page; after authenticating,
  the user lands back in the app with an active session.
- The user sees a list of workspaces they belong to, can create a new one, and can switch
  between workspaces.
- Inside a workspace, the user can upload a PDF and watch its ingestion status update (without
  manually refreshing) until it reaches `ready` or `failed` (with the failure reason shown, if
  failed).
- The user can type a search query, submit it, and see ranked results — each showing which
  document/page it came from, its content type, and content rendered appropriately (text
  excerpt, formatted table, or image reference/thumbnail).
- An owner can view and manage workspace members (invite by identifier, change role, remove).
- Errors (expired session, insufficient role, API failure) show a clear, non-technical message
  rather than a raw stack trace or a silently blank screen.

## Acceptance criteria

- [~] A real browser session can log in against the real Keycloak realm (no mocked auth) and
      reach an authenticated view of the app.
      **Not fully verified — no real browser available in this environment** (Playwright
      needs Node ≥20, this machine has 18.15.0; no Chrome/Edge/Chromium binary in PATH).
      HTTP-level evidence the flow is wired correctly: Keycloak's real OIDC discovery
      document matches `AuthProvider.tsx`'s configured `authority`; sending the exact
      authorization request `oidc-client-ts` would construct (`client_id=mm-rag-ui`, real
      `redirect_uri`, PKCE `code_challenge`+`S256`) returns a real Keycloak login page, not
      a client/redirect-uri error. **Needs a human to open `http://localhost:5173` and
      confirm end-to-end** before this is truly done.
- [~] A logged-in user can create a workspace, upload the existing `tests/fixtures/sample.pdf`
      fixture, watch its job status progress to `ready` against the real ingestion pipeline,
      and see it listed as a document — all against the real live stack, not fixtures/mocks.
      The underlying capability is real and integration-tested (`apps/api`'s routes this
      calls are exercised by 47 passing integration tests, including a real upload ->
      ingestion -> `ready` cycle); the *frontend* code path (`DocumentsTab.tsx`'s polling
      logic) typechecks and was written against the real API shapes, but wasn't watched
      render in a live browser — same gap as above.
- [~] A search query against that ingested document returns real results rendered with
      content-type-aware presentation, covering at least one text result, one table result,
      and one image result (`sample.pdf` has all three, per `050`/`051`'s fixtures).
      `ResultCard.tsx`'s three variants are written and typecheck against real
      `SearchResultOut` shapes (confirmed via `060`'s real search-report data showing all
      three content types); not visually confirmed in a live browser.
- [x] An owner can add a second member to a workspace and change their role; that member's
      access reflects the new role on their next request (matches existing RBAC semantics,
      no new authorization logic introduced client-side — the server remains the sole
      authority).
      The server-side mechanics this depends on (list/add/update-role, RBAC-gated) are
      live- and integration-test-verified (`070`/`071`'s combined regression run, 3 new
      tests in `test_workspace_members_route.py`). `MembersTab.tsx` composes these
      real, verified calls; UI-level exercise still wants a real browser per above.
- [ ] Logging out (or an expired/invalid session) prevents further authenticated actions and
      routes back to login, without leaking a previous session's data.
      Not verified — requires a live browser session to exercise sign-out and re-navigation.
- [x] The build produces static output only (`vite build`) — no Node process required to serve
      the app in production, matching the "no server-held secrets" constraint below.
      Verified: `npm run build` produces `dist/` static assets only; `vite preview` served
      them correctly.
- [x] `uv run pytest tests/unit` and the full existing integration suite still pass
      unmodified — this spec adds a new app, it doesn't touch `apps/api`'s or `packages/*`'s
      existing behavior.
      137 unit + 47 integration passed (this spec's one `apps/api` change — the members-list
      route — is itself covered by 3 of those integration tests; see `plan.md` for why it
      was added despite the "doesn't touch apps/api" framing above no longer holding
      literally).

## Constraints

- Never hold a provider API key (OpenAI, Qdrant, reranker) in this app — `06-security-model.md`
  §6, `CLAUDE.md`'s explicit convention. All provider calls happen server-side in `apps/api`/
  `workers`.
- Must call `apps/api` exclusively — no direct Qdrant/Postgres access from the browser.
- Must not implement its own authorization logic (e.g., hiding a button based on a
  client-computed role check as the *only* gate) — the server (`require_workspace_role`)
  remains the sole authority; client-side role-awareness is for UX only (what to show), never
  for enforcement.
- Must not require a Node.js server process at runtime — static build artifacts only, per the
  "plain React SPA via Vite" decision (as opposed to Next.js's SSR model).
- Depends on `070-api-hardening` being in place (or at least its CORS policy) before this
  app's browser traffic can reach `apps/api` from a different origin in a real deployment;
  local dev can proceed against `070`'s dev-default CORS setting.
- Local dev/test must stay runnable the way `061` verified it.

## Open questions

1. **Browser auth flow.** This app needs to authenticate against Keycloak from the browser.
   `packages/auth` today only *verifies* JWTs server-side (Resource Owner Password
   Credentials is used by tests/`eval/`, not appropriate for a real user-facing app). The
   standard, correct approach is OIDC Authorization Code + PKCE directly against Keycloak
   (e.g. via `keycloak-js` or `react-oidc-context`), which likely needs a new Keycloak client
   configured as "public" with PKCE enabled and this app's redirect URI registered — a
   Keycloak realm/client configuration change alongside the frontend code. Confirm the
   library/flow choice and the required Keycloak client setup in `plan.md` (this is an
   auth-adjacent change, so `plan.md` gets the explicit-approval treatment per `CLAUDE.md`'s
   ground rules even though no backend auth code changes).
2. **State/data-fetching approach.** A lightweight fetch-and-cache library (e.g. TanStack
   Query) for polling job status and caching workspace/document lists, vs. hand-rolled
   `useEffect`/`fetch` — affects how "watch status update without manually refreshing"
   (a Goal above) gets implemented. → `plan.md`.
3. **Component/styling approach.** A component library (e.g. shadcn/ui, Mantine) vs.
   hand-rolled components with plain CSS — given "not a design polish pass" is an explicit
   non-goal, leaning toward a lightweight component library to avoid spending this
   increment's effort on custom UI primitives. → `plan.md`.
