---
name: spec
description: Spec-driven development workflow for the MM-RAG platform. Use before implementing any new phase, service, or feature from the roadmap — turns a roadmap item or ad-hoc request into an approved spec.md, plan.md, and tasks.md under specs/, then hands off to implementation. Trigger on "/spec", "write a spec for X", "let's spec out X", "start phase N".
---

# Spec-driven development for MM-RAG

This project builds enterprise-grade features in small, reviewable increments. Nothing gets
implemented against this codebase without a written spec that the user has approved first.
This skill is the *only* on-ramp to writing code for a new capability — implementation work
that shows up without a spec should be redirected back through this workflow.

## Why this exists

The system being built (see `specs/architecture/08-roadmap.md`) touches auth, multi-tenant
data isolation, async infrastructure, and money-relevant retrieval quality. Silent scope
creep or undocumented decisions in this domain turn into security bugs or unreviewable
diffs. Writing spec -> plan -> tasks first keeps every change small enough to review and
gives the user a place to redirect *before* code exists, not after.

## Directory layout this skill maintains

```
specs/
  README.md                     # index of every spec, status, rubric/phase mapping
  templates/
    spec-template.md
    plan-template.md
    tasks-template.md
  architecture/                 # cross-cutting, living design docs (not per-feature)
    01-system-architecture.md
    02-data-model.md
    03-ingestion-workflow.md
    04-retrieval-design.md
    05-multimodal-strategy.md
    06-security-model.md
    07-evaluation-observability.md
    08-roadmap.md
    09-repo-and-module-structure.md
  <NNN>-<slug>/                 # one folder per feature/phase spec
    spec.md
    plan.md
    tasks.md
```

- `specs/architecture/*` are the standing design references. Read the relevant ones before
  writing any new spec — a new spec should *extend* these, not contradict them. If a spec
  reveals that an architecture doc is wrong or outdated, update the architecture doc in the
  same session and say so explicitly.
- `specs/<NNN>-<slug>/` folders are per-increment. `NNN` is a zero-padded sequence number
  (`010`, `020`, ...) allocated in `specs/README.md`, leaving gaps for insertions. `slug` is
  kebab-case (e.g. `010-async-ingestion-pipeline`).

## The workflow

Run these stages in order. Stop and wait for explicit user approval between stage 1 and
stage 2 — everything after that can move faster once the spec is approved, but always show
the plan before writing tasks if the plan required any non-obvious technical judgment call.

### Stage 1 — spec.md (the WHAT and WHY, no implementation detail)

1. Identify which roadmap phase or ad-hoc request this covers. Read
   `specs/architecture/08-roadmap.md` and the relevant architecture doc(s).
2. Copy `specs/templates/spec-template.md` to `specs/<NNN>-<slug>/spec.md` and fill it in:
   problem statement, in/out of scope, user-facing behavior, acceptance criteria (testable),
   open questions.
3. Do **not** name specific libraries, schemas, or file layouts here beyond what's already
   fixed in the architecture docs. A spec should be readable by someone deciding *whether*
   to build this, not *how*.
4. Present the spec to the user for approval (surface it directly in chat — don't just say
   "I wrote it"). Do not proceed to Stage 2 until they approve or request changes.

### Stage 2 — plan.md (the HOW)

1. Only after spec approval. Copy `specs/templates/plan-template.md` to
   `specs/<NNN>-<slug>/plan.md`.
2. Translate the spec into concrete technical decisions: which module/service owns this,
   data model changes (as a diff against `specs/architecture/02-data-model.md`), API
   contract (request/response shapes, new endpoints), retrieval/ingestion changes, migration
   strategy, rollout/flag strategy, and a risk list.
3. Every decision that deviates from or extends an architecture doc must say so and update
   that doc (or flag it for the user to confirm the update).
4. If the plan is small and obvious (pure extension of an already-approved pattern), you may
   summarize it in chat instead of pausing — but still write plan.md. If it involves a new
   dependency, a schema change, or touches auth/tenant-isolation, pause for explicit approval.

### Stage 3 — tasks.md (the ORDER)

1. Copy `specs/templates/tasks-template.md` to `specs/<NNN>-<slug>/tasks.md`.
2. Break the plan into an ordered checklist of small, independently-testable tasks. Each task
   names the files it touches and how it will be verified (test, manual check, curl command).
3. Group tasks so that the system stays runnable after each group — never leave a task list
   that requires three unfinished tasks before anything works again.

### Stage 4 — implement

1. Work through `tasks.md` top to bottom, checking items off (`- [x]`) as you go using Edit,
   not by rewriting the file.
2. If reality forces a deviation from plan.md (an API doesn't behave as assumed, a library is
   missing a feature), stop, update plan.md with the change and why, then continue — don't
   let the plan silently rot.
3. Update `specs/README.md`'s status column when a spec moves between `draft` / `approved` /
   `in-progress` / `done`.

## Ground rules

- One spec folder = one coherent increment. If a request spans multiple roadmap phases,
  split it into multiple `NNN-slug` folders up front rather than writing one giant spec.
- Specs are living documents during Stage 1-3 (edit freely with the user), but once
  implementation starts (Stage 4), treat spec.md as frozen scope — new requirements become a
  new spec, not silent edits to a "done" spec.
- Multi-tenancy, auth, and retrieval-filter changes always require a plan.md, even for a
  change that looks tiny — this is the category of bug that leaks one tenant's data to
  another.
- When in doubt about scope size, prefer more/smaller specs over fewer/larger ones.
