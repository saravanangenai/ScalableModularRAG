# Plan: <title>

- **Spec:** `spec.md` (must be approved before this file is written)
- **Status:** draft

## Summary

One paragraph: the technical approach in plain language.

## Architecture doc deltas

List every `specs/architecture/*.md` file this plan changes or extends, and what changes.
If none, say "none — pure extension of existing patterns."

| Doc | Change |
|---|---|
| `02-data-model.md` | ... |

## Component/module ownership

Which service/module (per `09-repo-and-module-structure.md`) owns each piece of new
behavior. Call out any new module boundary being introduced.

## Data model changes

New tables/columns, new Qdrant payload fields, new payload indexes. Include the migration
approach (additive vs. breaking) and backfill strategy if existing data needs updating.

## API contract

New/changed endpoints: method, path, auth requirement, request shape, response shape, error
cases. This is the contract the frontend and tests will be written against.

## Retrieval / ingestion impact

If this touches retrieval or ingestion: what changes in the pipeline, expected effect on
latency/cost/quality, and how it's measured (link to eval plan if relevant).

## Security / tenancy impact

Does this touch auth, authorization, or the mandatory tenant/workspace retrieval filter? If
yes, spell out exactly how isolation is preserved. If no, say so explicitly — don't leave it
implicit.

## Rollout

Feature flag / staged rollout / big-bang. What happens if this needs to be reverted.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| | | | |

## Alternatives considered

Briefly, what else was considered and why this approach won.
