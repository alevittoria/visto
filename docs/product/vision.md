# Product intent

## Direction

Python/FastAPI, React/TypeScript and SQLite with Clean Architecture, so
integrations (device platform, AI provider, storage) stay replaceable and the
code maintainable. Development uses role-based AI coding agents with a small set
of companion documents.

The runtime should act like a conversation: see the screen, decide what to do,
execute through the platform's automation libraries, wait, see the next screen and
judge the effect before choosing the next action. AI owns application-level
verification as well as navigation. Avoid mixing AI interpretation with
hard-coded semantic completion rules.

## Intended interaction

1. User selects a device and describes a goal and constraints.
2. AI examines a fresh screenshot and available technical tools.
3. AI evaluates the previous effect, updates its working plan and proposes one
   action, a bounded observation wait, a question or a conclusion.
4. Application validates the technical request, executes it and records results.
5. Fresh screenshots and tool outcomes continue the same logical conversation.
6. A terminal AI assessment explains passed, failed or inconclusive with evidence.

## Success means

- A task can succeed across different valid UI structures without new Python
  rules for control captions, page titles, selected flags or app-specific screens.
- Failure reports distinguish a product failure, insufficient evidence, device or
  provider failure and user cancellation.
- Every decision and conclusion can be traced to the user's goal and observed
  images; confidence is not a guarantee or a substitute for evidence.
- Changing provider, device backend or storage does not change the core use case.

## Engineering defaults

Start local-first, one device per run, one AI conversation, one action then a new
observation. Use a simple composition root and explicit dependency injection.
Measure real provider/device behavior before treating the product as accepted.
Observations are screenshots. Accessibility trees
could later be optional observation data, never a mandatory semantic verifier.

## Out of scope for now

Acceptance thresholds are agreed before labelled evaluation. Deterministic
replay, cloud deployment, multi-user scheduling and a runtime team of AI agents
are out of scope. A runtime report is not proof of invisible
backend state that was never observed.
