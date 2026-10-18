# Runtime data model

Plain Python frozen/slots value classes under `backend/src/visto/domain/`
and framework-independent application ports. SDK objects never cross the
application boundary. See [architecture](03-architecture.md).

| Value | Minimum fields and meaning |
|---|---|
| Goal | Exact original prompt text, optional expected result and immutable constraint tuple; kept separate from the working plan |
| Run | `run_id`, `device_id`, immutable Goal and configuration snapshot, lifecycle state, revision, timestamps, pending question and terminal record |
| Run configuration | Technical limits, tool capabilities, instruction version, provider/model identity, adapter versions; no credentials |
| Observation | `observation_id`, `run_id`, sequence, capture time, screenshot artifact reference, image dimensions/orientation, device/session identity, optional technical metadata |
| Action | `action_id`, `run_id`, source `decision_id` and `observation_id`, typed command and arguments, bounded timeout |
| TechnicalReceipt | `action_id`, dispatch/start/end times, status (`completed`, `rejected`, `error`, `uncertain`), sanitized error/details |
| AgentDecision | `decision_id`, `run_id`, input observation/evidence IDs, previous-effect assessment, concise rationale, updated working plan, one typed next decision, usage/model metadata |
| Effect assessment | Previous `action_id` if any, AI judgement (`achieved`, `not_achieved`, `unclear`), explanation and evidence IDs; optional on initial turn |
| Assessment | AI verdict (`passed`, `failed`, `inconclusive`), concise explanation, referenced observation IDs, associated `decision_id` |
| PendingQuestion | `question_id`, `run_id`, source `decision_id`, question text, creation time, answered/cancelled state and attributed answer when supplied |
| Artifact reference | Artifact ID, media type, byte length, content hash, storage key; portable reference rather than public path/URL |

Concrete modules: `commands.py` contains typed device operations; `models.py`
contains request/configuration/evidence/decision/receipt values; `run.py` contains
the lifecycle and terminal variants; `validation.py` checks contextual references.
`application/context.py` binds already-resolved image bytes to stored hashes and
their observations. `application/ports.py` declares asynchronous I/O boundaries.

The outer `adapters/command_codec.py` provides an explicit JSON-compatible
technical-command round trip only. It rejects unknown kinds/keys and does not
define a provider or future run API schema. Inner layers import standard library
and inward packages only; the import guard tests relative imports too.

`AgentDecision.next` is a discriminated union: `act(command)`,
`observe_after(delay_ms)`, `ask_user(question)` or `conclude(Assessment)`. This is
a technical tool protocol, not a taxonomy of semantic test steps. `ask_user`
records one pending question and transitions to `waiting_for_user` without device
actions. An answer is appended as user-attributed clarification, preserving the
original goal/constraints; contradictory replacement objectives require a new
run. The AI may conclude inconclusive when essential evidence remains unavailable.

Device commands are a deliberately small allowlist: `tap`, `long_press`,
`swipe`, `type_text`, `back`, `home`, `enter`.
Coordinates use the source observation's image frame; adapters must map and
validate orientation/dimensions or reject stale/unsupported requests. Device
selection and session setup are control-plane operations. App launch or other
commands are added only with explicit capability/argument contracts. Never expose
arbitrary shell or Python execution to the product AI.

## Lifecycle and terminal records

Lifecycle: `created -> running`, with `running -> waiting_for_user` for a question
or `running -> paused` for a user pause. Answer/resume reacquires device ownership
and obtains a fresh observation before returning to the conversational decision
loop. No stale action is replayed. Suspension releases the lease after settling
any in-flight receipt; wall-time budget continues, while unused action/inference
counters do not advance. Question replies and resume requests are run-scoped and
idempotent. Cancellation, deadline expiry or technical failure can terminate a
suspended run. Any active state can reach `terminal`, whose record is one of:

- `ai_conclusion`: contains exactly one AI `Assessment`.
- `infrastructure_failure`: component, sanitized error and available evidence.
- `cancelled`: requester/source and time.
- `budget_exhausted`: exhausted technical budget and usage at stop.

Technical stops carry no synthetic semantic verdict. Prior AI assessments remain
history and do not override the terminal reason. Finalization is atomic and
idempotent; cancellation and an arriving conclusion must not produce two terminal
records. The selected contract is first-terminal-wins: `Run.finish()` preserves
its existing result; `RunStore.finalize()` enforces atomicity across writers
and returns the actual winning Run in the SQLite implementation.

## Invariants and evidence

- Original goal/constraints are immutable; derived working plans are revisioned
  decision data. A changed user goal requires a new run in the initial version.
- IDs and references are scoped to the run. A conclusion references at least one
  persisted observation actually supplied in its decision context. Validate
  reference integrity in code; assessing whether the image proves the claim is
  the AI's job.
- A command is bound to its source observation and run/device lease. Its receipt
  is recorded even when execution fails; capture failures are explicit errors,
  never empty screenshots presented as valid observations.
- `completed` means technical execution completed according to the adapter;
  `uncertain` means the effect is unknown. Neither means application success.
- Persist a decision's presented evidence IDs, instruction/model identity and
  concise rationale. Do not request or store hidden chain-of-thought.
- Store structured records in SQLite and image bytes in local artifact storage.
  Keep hashes/references consistent; a missing/corrupt artifact is explicit.
  Schema/migrations, exact limits and cleanup policy belong to implementation.

All configured technical limits are explicit integer milliseconds/counts, without
invented runtime defaults. Booleans are not accepted as integers. Screenshot
commands use source-image pixel coordinates; bounds, command capabilities,
run/device/session/lease bindings and actually presented evidence are technical
validation. Pixel/text meaning is never examined by these contracts.

`Run.resume()` clears the active question. The implemented application loop must
append question/answer records before changing state and construct subsequent
AgentContext with attributed answers from durable history.

Screenshots, entered text and model context may contain private application data.
Local artifacts and metadata must not be assumed safe to commit or expose through
an unauthenticated API. Credentials are injected into adapters and excluded from
configuration snapshots, reports and logs. Retention and provider transmission
are documented in [artifact storage](../artifact-storage.md).
