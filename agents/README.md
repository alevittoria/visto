# Development agent team

Development roles for building Visto with AI coding agents. The product
runtime uses one conversational AI; it does not run this team against the device.

## Roles

| Role | Responsibility | Brief |
|---|---|---|
| Coordinator | Task breakdown, assignment, integration and STATUS | [coordinator](roles/coordinator.md) |
| Architect | Domain contracts, dependency direction and design decisions | [architect](roles/architect.md) |
| Backend | Use cases, API and persistence adapters | [backend](roles/backend.md) |
| AI runtime | Conversation, provider adapter and AI evidence | [ai-runtime](roles/ai-runtime.md) |
| Android | Device observation, sessions and typed commands | [android](roles/android.md) |
| Frontend | React console, controls and evidence inspection | [frontend](roles/frontend.md) |
| QA | Independent review, protocol checks and labelled evaluation | [qa](roles/qa.md) |
| DevOps | Local setup, dependency locks and developer checks | [devops](roles/devops.md) |

A role is a brief, not a permanently running process or a separate model. Roles
can be reused for sequential tasks. File ownership is assigned per task.

## Assignment workflow

1. The coordinator splits the request into tasks and identifies independent ones.
2. Before starting a worker, state role, read set, exact write set, dependencies,
   deliverable and verification. Reserve one writer per path.
3. Delegate independent substantial work using the role brief; keep trivial and
   dependent work local. Respect the tool's concurrency limit. No nested
   delegation unless explicitly assigned.
4. Workers implement only their slice and report back: files changed, checks with
   actual results, limits and follow-ups. No handoff files are written.
5. The coordinator integrates and assigns an independent review. A reviewer does
   not certify their own implementation; review is read-only until a bounded fix
   is assigned.
6. The coordinator runs `python scripts/verify.py`, updates STATUS if needed and
   stops every worker before ending.

Assignment example:

```text
Role: android
Read: AGENTS.md, agents/roles/android.md, <relevant docs and contracts>
Write: <exact source/test paths>
Depends on: <contract or prior change>
Deliver: <bounded adapter behavior>
Verify: <specific local fake checks; name live prerequisites if applicable>
Limits: no STATUS edits, no nested delegation, no unrelated changes
```

Every worker follows the device- and app-anonymity rules in `AGENTS.md`.

## Codex profiles

[`codex/`](codex/) contains TOML profile templates using the documented `name`,
`description` and `developer_instructions` fields
([custom-agent reference](https://learn.chatgpt.com/docs/agent-configuration/subagents)).
They reference the local briefs and deliberately set no model, reasoning effort
or permissions. To register them natively, copy them into your own `.codex/agents/`;
otherwise pass the brief explicitly when delegating.
