# Architect

## Scope

Define small domain/application contracts and inward dependencies for the conversational Android runner.

## Read set

Start with the context router and STATUS; then load only:
docs/product/vision.md; docs/ai-context/03-architecture.md;
docs/ai-context/06-data-model.md; docs/ai-context/07-integrations.md.
Read additional decision records only when the task identifies existing files.
The task assignment may narrow or extend this read set explicitly.

## Write ownership

Only assigned architecture docs/ADRs and explicitly allocated domain/application contract files; do not silently change shared contracts.
Every assignment must name exact paths; role scope alone grants no write ownership.

## Expected work

- Model goal, observation, decision, typed command, technical result, evidence and terminal outcome without app-specific predicates.
- Keep domain/application free of FastAPI, Appium, provider SDK and database imports; justify each abstraction against a use case.
- Document failure semantics, cancellation and dependency trade-offs so adapter owners can implement independently.

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
