# Conventions

- Code, commits and docs in English.
- Preserve product intent in `docs/product/vision.md`.
- Domain/application use typed, framework-independent contracts. External
  dependencies live at the edges; composition selects concrete adapters.
- Inner values use frozen/slots stdlib dataclasses and immutable tuples.
  Constructors/context validators check technical types and references; type
  annotations alone do not validate input. Millisecond/count limits are explicit
  integers, excluding booleans. Wire mapping stays in outer adapters.
- Runtime semantic verification belongs to AI. Technical validation must not
  expand into app-specific test-success predicates.
- Report real commands and results. Planned checks and mocked behavior are not
  live evidence. Do not use test counts as evidence of model judgement quality.
- Version runtime instructions, model identity and observation references. A new
  instruction version is a new file in `backend/prompts/`; recorded runs keep theirs.
- Never store raw secrets in prompts, fixtures or documentation.
- Use one Visto home per host so all processes share
  `<home>/data/device-leases`. Never auto-clear uncertain ownership or replay an
  interrupted mutation.
- Provider errors expose explicit safe codes; raw exception/refusal bodies and
  credentials never become terminal details. A UTF-8 `--request-file` keeps
  quotes/Unicode intact across shell argument parsing.
- Docs describe current behavior only; history belongs in Git.
