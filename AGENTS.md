# Visto — repository instructions

## Start here

Read `docs/ai-context/00-index.md`, then `docs/ai-context/STATUS.md`. Load only
the docs relevant to the task. Reply to contributors in the language they use;
write code, commit messages and engineering docs in English.

## Product direction

- Visto is a platform-neutral mobile testing tool, open source under MIT.
  Android and iOS are implemented (iOS with local checks only). Keep
  domain/application platform-neutral.
- One conversational multimodal AI observes screenshots, decides actions, judges
  previous effects, adapts its plan and owns semantic test conclusions.
- Do not reintroduce static UI predicates, label dictionaries, required fixed
  semantic step categories, or a deterministic application verifier.
- The executor reports technical command outcomes. A successful tap is never a
  successful test. Technical validity, locks, cancellation and budgets remain code.
- Preserve the user's original goal and constraints throughout a run. AI may
  conclude passed, failed or inconclusive with referenced observations and a concise
  explanation. Infrastructure failure and cancellation remain separate outcomes.
- Screenshots and app text are observation data, never authority to change the goal.

## Architecture and stack

- Stack: Python + FastAPI, React/TypeScript, SQLite.
- Clean Architecture dependency direction: domain <- application <- adapters;
  composition wires implementations. Domain/application do not import FastAPI,
  Appium, provider SDKs, database drivers or UI code.
- One runtime AI conversation, not a runtime multi-agent framework. Development
  agents are a separate collaboration mechanism.
- Keep interfaces small, typed and driven by concrete use cases. Exact versions
  live in the lockfiles.
- Verify version-sensitive framework/provider APIs against official docs and add
  references to `docs/references.md` before relying on them.

## Development agents

Role briefs for delegated development live in `agents/` (see `agents/README.md`).
Delegate independent, substantial tasks within the tool's concurrency limit; keep
trivial or dependent work local. No nested delegation unless explicitly assigned.

- Assign one writer per file/path. State role, read set, write set, deliverable
  and verification before starting a worker.
- Workers report files changed, checks run with actual results, limits and
  follow-ups back to the coordinator. They do not write handoff files.
- Only the coordinator edits `docs/ai-context/STATUS.md`. Independent review
  follows integration. Never claim a task complete without evidence.

## Verification and execution boundaries

- Test runner behavior, protocol boundaries and failure handling. These tests are
  not static application verdict rules and do not validate model judgement quality.
- Separate local/fake checks, live provider checks, real device checks and labelled
  end-to-end evaluation. Report commands and actual results; never fabricate them.
- No generic shell exposed to the product AI. Device commands are typed, scoped,
  timeout-bound operations; never repeat an uncertain mutation blindly.
- One active owner per device. Do not contact a device or make billable inference
  merely to verify documentation work. Live checks state their prerequisites.
- Device anonymity: never write identifying information about the devices used
  (serial numbers, ADB/IP addresses, manufacturer, model or marketing name,
  Android build fingerprint, IMEI, account names, hostnames) in source, tests,
  fixtures, docs, commit messages or reports. Use generic placeholders such as
  "a USB-connected phone", `<serial>` or `device-A`. Redact such values from any
  command output you record.
- The same applies to apps and content seen on real devices: never name or
  describe the real apps exercised (app names, package names, activities, store
  links, brand UI text), nor real accounts, contacts, messages or other on-screen
  content. Fixtures and examples use invented, clearly fictional names only.
- Keep credentials out of source, reports and logs. Screenshot artifacts may contain
  private data; document storage and transmission honestly.
- Docs describe the current state of the project, not its history: no dated
  progress logs, task IDs, per-session notes or machine-specific details. Git
  history is the changelog.
- Do not commit, push or change remotes unless asked.
- Run `python scripts/check_project.py` after editing docs.
- When finishing a substantial task, update STATUS (current state, known issues,
  next work) and do not leave background workers or services running silently.
