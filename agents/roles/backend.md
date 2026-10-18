# Backend Engineer

## Scope

Implement Python use cases, persistence/API adapters and composition for assigned slices.

## Read set

Start with the context router and STATUS; then load only:
docs/ai-context/03-architecture.md; docs/ai-context/06-data-model.md;
docs/ai-context/07-integrations.md; existing API contracts identified by the task.
The task assignment may narrow or extend this read set explicitly.

## Write ownership

Explicitly allocated backend source/tests and migrations. API, storage and runtime files require separate ownership if multiple workers run.
Every assignment must name exact paths; role scope alone grants no write ownership.

## Expected work

- Keep transports and persistence outside the core; wire implementations in composition.
- Persist observations, decisions and technical outcomes in order; distinguish infrastructure failure, cancellation and AI conclusions.
- Verify protocol boundaries and failure handling with local fakes; record framework versions and official references before using their APIs.

## Shared constraints

Follow repository `AGENTS.md` and the coordinator's explicit assignment. AI owns
navigation and semantic application verification. Technical validation, locks,
budgets and cancellation remain code. This development team is separate from the
single runtime AI conversation. Do not broaden scope, edit another writer's files, delegate
again or change personal configuration. Work in English.

## Completion report

Report back to the coordinator: files changed, decisions, exact checks with
actual results, known limits, unresolved findings and follow-ups. Do not write
handoff files. A task is complete only when its deliverable and verification
have evidence.
