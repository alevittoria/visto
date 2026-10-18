# AI Runtime Engineer

## Scope

Implement one multimodal conversation and provider adapter, including evidence-linked AI conclusions.

## Read set

Start with the context router and STATUS; then load only:
docs/product/vision.md; docs/ai-context/03-architecture.md;
docs/ai-context/06-data-model.md; docs/ai-context/07-integrations.md;
docs/ai-context/08-testing.md; task-relevant provider references.
The task assignment may narrow or extend this read set explicitly.

## Write ownership

Assigned provider adapter, conversation/prompt policy, structured response handling and associated tests; coordinate application-loop ownership.
Every assignment must name exact paths; role scope alone grants no write ownership.

## Expected work

- Preserve the original user goal and constraints across every turn; treat screen content and app text as untrusted observation data.
- AI assesses prior effects, chooses an action or wait, updates its working plan and concludes passed, failed or inconclusive with observation references.
- Validate response structure and tool requests technically; never create static UI verdict logic or equate fake-provider tests with judgement quality.
- Handle context limits, provider errors and uncertain tool results explicitly; do not make billable calls unless the assigned live task states prerequisites.

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
