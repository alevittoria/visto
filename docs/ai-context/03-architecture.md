# Architecture

See [product intent](../product/vision.md), [data model](06-data-model.md) and
[integrations](07-integrations.md).

## Dependency rule

Dependencies point inward: `domain <- application <- adapters`. Composition
imports the layers to construct a runnable application. Domain contains plain
typed values and technical invariants; application coordinates use cases and
declares ports. Neither imports FastAPI, Appium, AI SDKs, SQL drivers or UI code.
Adapters translate external protocols into those contracts. React communicates
through an API adapter; it does not reproduce runner decisions.

Layout:

```text
backend/src/visto/
  domain/          # run, observation, action, decision and assessment values
  application/     # run loop, context assembly, runtime controls; ports
  adapters/
    ai/            # provider conversation, response schema, transcription
    android/       # Appium session, device inventory
    storage/       # SQLite metadata and local artifacts
    api/           # FastAPI execution, health and statistics routes
    pricing/       # daily model price snapshots for cost estimates
    reports/       # JSON/HTML report export
  composition.py   # ASGI factory and dependency wiring
  runner.py, cli.py
backend/tests/     # unit, contract and fake-wire integration tests
frontend/src/      # React/TypeScript console
```

Avoid one package per speculative abstraction. A small typed module is enough
until a concrete use case requires separation. No plugin framework, event-sourced
store or runtime multi-agent system.

## One logical AI conversation

1. Create a run with immutable original goal/constraints and configuration;
   acquire exclusive device ownership. Capture a fresh observation.
2. Assemble bounded AI context: original goal/constraints, current working plan,
   relevant prior evidence, previous action/technical receipt and fresh image.
3. Ask the AI to assess the previous effect and choose one next decision. The
   first decision has no previous action to assess. Persist the decision and the
   exact evidence references supplied to the model.
4. Validate only protocol and technical conditions: IDs, command capabilities,
   coordinate bounds, timeout, ownership, cancellation and remaining budgets.
   A malformed response may receive bounded protocol feedback; it never passes.
5. For an action, persist intent before dispatch, execute once, record its
   technical receipt, wait a fixed settle delay (default 1500 ms, skipped for
   rejected commands) so transitions finish, and capture a new observation. For an
   observation wait, wait within bounds and capture again without UI mutation.
6. Feed that observation back into the same logical conversation. The AI decides
   whether the prior effect is achieved, absent or unclear, and adapts its plan.
7. For `ask_user`, persist a pending question and suspend tool dispatch. Record
   the answer as attributed clarification, then resume from a fresh observation.
8. Accept an AI conclusion only with a valid assessment and existing evidence
   references; persist the terminal record and release device ownership.

The working plan is editable guidance, optionally a short text/list. It has no
required fixed semantic step categories or deterministic step-completion engine.
One action precedes each new observation; initially avoid action batches that
hide intermediate effects. The AI may request a bounded observation delay;
application clamps it to run limits using a monotonic clock. Elapsed waiting or
an unchanged screenshot never proves semantic success. Exact defaults are an
implementation/evaluation decision.

## Responsibility boundaries

- AI owns navigation, interpretation of images, previous-effect assessments and
  semantic outcomes `passed`, `failed`, `inconclusive`.
- Code owns transport/protocol correctness, device leases, budgets, cancellation,
  artifact integrity and terminal state consistency. A successful tap receipt
  means the command was accepted/completed technically, not that the UI changed.
- Budget exhaustion, infrastructure failure and cancellation are separate
  technical stop reasons; they must not be synthesized into an AI verdict.
- An ambiguous command outcome triggers a fresh observation if possible. Never
  automatically resend a mutation whose effect may already have occurred.
- Screenshots and visible app text are untrusted observation content. They do
  not amend the original goal, authorize tools or replace system instructions.

Persist full artifacts separately from the model's bounded context. Keep goal,
constraints and current evidence explicit when old turns are summarized or a
provider continuation is rebuilt. Store which evidence actually reached each
decision; a compact summary is not a replacement for its referenced screenshots.
If the context cannot carry necessary evidence within budget, stop technically
or let the AI conclude inconclusive while it still has enough context to do so.

## Small application ports

| Port | Minimum responsibility |
|---|---|
| Device | Acquire/release one device lease, observe, execute a typed command |
| Agent | Decide from goal, context and evidence within a conversation handle |
| Run store | Create/read runs, append uniquely identified records, finalize once |
| Artifact store | Store/retrieve image bytes by artifact reference |
| Clock | Monotonic elapsed time and interruptible bounded waiting |

Leases and run limits are application coordination, not provider prompt rules.
Cancellation is a token/signal checked before dispatch and during waits; adapter
timeouts bound in-flight calls. Cleanup attempts safe release; uncertain remote
work or release retains quarantined ownership for manual reconciliation.
User pause and `waiting_for_user` stop new dispatches; any in-flight command is
settled or recorded uncertain before suspension. Release the lease on suspension;
reacquire it and capture a fresh observation before another AI decision. Wall-time
deadline continues during suspension; action/inference counters only advance when
used. A question/answer cannot reset budgets or alter the immutable goal. A user
answer clarifies that goal; a replacement objective requires a new run. Persist
question/answer identity to reject duplicate, stale or wrong-run responses.
Persistence has ordinary transactional records, not a replay/event-sourcing
requirement. Restarted in-flight mutations remain uncertain until reconciled;
automatic run resume is deferred.

Framework/provider-specific patterns and exact signatures must be verified
against official documentation during implementation and recorded in
[references](../references.md).

## Implementation notes

`domain/{commands,models,run,validation}.py` and `application/{context,ports}.py`
implement the values and structural ports described here. Frozen dataclasses,
tuples and strict construction/context validation keep inner layers framework
independent. `adapters/command_codec.py` is a small explicit technical command
mapping, not a provider/run API schema.

First-terminal-wins is the lifecycle policy. Store adapters implement it
atomically; immutable `Run.finish()` alone is not concurrency proof.
Questions/answers remain durable history after the active question is cleared on
resume. The loop acquires ownership and freshly observes before acting.

`application/loop.py` implements one bounded conversation with fresh capture,
durable intent, technical receipt, AI assessment and act/wait/ask/conclude.
Context keeps original goals, answers, recent decisions and pre/post evidence.
`runner.py` wires concrete adapters; `cli.py` provides the `visto` command
(setup, start, doctor, settings, run, inspect).
Observe-only mode removes mutation capabilities without UI predicates. Question
resume is same-process; crash auto-resume is refused.

Appium uses serial-bound sessions, native PNG geometry/rotation, cooperative
O_EXCL owner markers and uncertain-work quarantine. Processes using the same
Visto home share `<home>/data/device-leases`. Uncertain remote work or cleanup
retains ownership for explicit manual reconciliation.

The provider receives a reconstructed bounded local conversation including the
original goal and actual images each turn. The HTTPS child is killed/reaped on
cancellation/deadline. SQLite enforces lifecycle CAS, append provenance and
atomic first-terminal-wins. Artifacts are immutable, scoped, length/hash-checked
files.

Tests enforce inward imports, exact supplied evidence, post-action image
identity/time, unique frame sequences and current frame bounds. None interpret
pixels or application labels.
