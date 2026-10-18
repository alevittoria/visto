# AI judgement evaluation protocol

Status: design only; no labelled evaluation has been run yet. The
[scenario matrix](scenarios.json) contains synthetic scenario specifications, not
screenshots, runnable fixtures or results. Record each run with the
[run template](run-template.md). The [testing router](../ai-context/08-testing.md) distinguishes the
software checks from live and semantic evaluation.

## Questions to answer

1. Can the AI reach the requested observable result across UI variations?
2. Can it recognize a failed result without declaring success after a successful
   technical command or a misleading confirmation screen?
3. Can it stop as inconclusive when evidence is inadequate, without inventing
   invisible backend facts?
4. Does it preserve the original objective and constraints when app content tries
   to redirect it, an operation is uncertain or context is compacted?
5. What time, inference cost and action count does that quality require?

An evaluation harness may hold deterministic ground truth and compare recorded
outcomes for measurement. Those labels and harness checks are offline evaluation
mechanisms. They must not be injected as a static semantic verifier into product
execution, and they must not be visible to the runtime AI.

## Evidence classes

| Class | Purpose | Claim permitted |
|---|---|---|
| Local software/fake | State machine, boundary parsing, lock/cancel/budget/error behavior | Code behaves on specified inputs |
| Offline screenshot/trajectory set | Agent interpretation on fixed labelled images and history | Judgement on those recorded observations |
| Live provider smoke | Adapter accepts images, returns a valid decision, records usage | This provider integration works in this configuration |
| Real device smoke | Actual typed commands and observations travel end to end | This device integration works in this configuration |
| Labelled live end-to-end | Navigation and judgement on resettable scenarios | Measured model/system quality for that suite |

Offline trajectory results do not establish navigation quality on a live device.
Infrastructure failures, budget exhaustion and user cancellations are reported separately; they are
not quietly converted into failed app assertions or removed to improve scores.

## Scenario preparation and labelling

Each scenario needs an immutable ID/revision, original user prompt, initial
state/reset method, app build, locale/display/device configuration, reproducible
fault setup where relevant, expected observable evidence and a withheld label.
Specify which observations would justify passed, failed or inconclusive. A
scenario with an actually failed objective but insufficient visible evidence
should expect inconclusive; the AI is not expected to know hidden state.

Start from the paired positive/negative controls in `scenarios.json`. Materialize
screenshots and/or a small controllable Android fixture before executing them.
Keep setup and label code outside domain/application runtime packages. Include
UI wording/layout variations without changing the underlying objective. Include
different data and scenarios held out from prompt development.

Have a human label the scenario independently of the actor's conclusion. For
disputed labels or high-impact false success cases, obtain a second human review
and record the disagreement and resolution. Never silently relabel a scenario to
match model output. Human review must distinguish observed evidence from hidden
fixture truth. Do not treat model confidence as a label.

## Run procedure

1. Freeze suite, labels, app build, system prompt hash, tool schema hash, model
   identifier/revision where available, provider/API version, parameters and code
   revision. If no commit exists, use a source artifact hash and state that fact.
2. Declare repetitions, per-run time/action/token/spend limits and promotion
   thresholds before the measurement batch. Thresholds are currently undecided;
   exploratory runs must be labelled exploratory.
3. Verify reset and device ownership. Use disposable test data and accounts.
   Record screen dimensions, orientation, locale, Android/Appium versions and
   network conditions. Confirm the privacy/transmission configuration.
4. Execute local software checks before live work. Run provider and device smoke
   separately so their failures remain diagnosable.
5. Randomize scenario order where practical. Reset between repetitions and
   preserve failures; never rerun only a failure and retain only its success.
6. Save each complete run, score against withheld labels, then review false passes
   and ambiguous evidence. Keep the actor's original assessment unchanged.
7. Publish counts, denominators, uncertainty and costs. Compare changed systems
   on the same scenario revisions and settings, including negative controls.

Repeat each scenario across independently reset runs; choose the repetition
count before execution, based on the decision being made. A single success is
an anecdote. Group results by scenario as well as repetition: repeated runs of
one scenario are not equivalent to independent coverage of many scenarios.

## Required run record

- Run/scenario/repetition IDs, timestamps, all configuration hashes and resolved
  model identifier; no secrets. Record provider aliases that may change.
- Original goal/constraints, retained conversation context and any summaries,
  ordered observation IDs and image hashes, capture timestamps and geometry.
- Each AI decision with supporting observation references, requested typed action,
  technical result, elapsed time and the following observation. Do not request
  or store hidden chain-of-thought; a concise decision explanation is sufficient.
- Terminal assessment with concise evidence-based explanation, or separate
  `infrastructure_failure`, `cancelled` or `budget_exhausted` termination.
  Preserve partial trajectories and prior AI assessments without converting a
  technical stop into an AI verdict.
- Actual usage from provider where supplied: input/output/image/cached usage as
  available, calls, latency, action count and wall time. Mark unknowns as unknown.
- Estimated monetary cost with pricing source/date/currency and method; never
  present an estimate as a provider invoice.
- Withheld expected label, adjudication notes, disagreement category, artifact
  storage/access/retention/deletion and whether screenshots left the machine.

## Metrics and denominators

Always publish raw counts next to rates, separated by scenario family and
configuration. Preserve a confusion table over expected/actual passed, failed
and inconclusive, plus separate counts of infrastructure failures, budget
exhaustion and cancellations.

| Metric | Definition |
|---|---|
| False-pass rate on observable negatives | Runs returning passed where the withheld expected label is failed / all valid runs labelled failed |
| Unsupported-pass rate | Runs returning passed where expected label is inconclusive / all valid runs labelled inconclusive |
| False-fail rate on positives | Runs returning failed where expected label is passed / all valid runs labelled passed |
| Positive completion rate | Runs returning passed where expected label is passed / all valid runs labelled passed |
| Inconclusive rate | Runs returning inconclusive / all valid semantic-evaluation runs; also report per expected label |
| Evidence support | Reviewed terminal assessments whose cited images support the claims / reviewed terminal assessments, with sample selection recorded |
| Reliability and limits | Infrastructure failures, budget exhaustion and cancellations / all attempted runs, each separately |
| Efficiency | Calls, actions, elapsed time and measured/estimated cost by scenario and outcome; report median and tail where sample size permits |

Here valid means a run for which semantic judgement was reached or explicitly
inconclusive, excluding infrastructure failures, budget exhaustion and cancellations from the semantic
denominator only. Publish excluded counts and all-attempt rates alongside it.
If a denominator is zero, report not applicable, not zero percent. Include the
false-pass count over all actual passed conclusions to show the risk a user sees.
Report statistical uncertainty for measured rates using a declared method and
acknowledge shared-scenario dependence. Zero observed errors does not establish
zero error probability. No percentage here constitutes an acceptance threshold.

## Correlated actor/judge errors

The same AI chooses actions and judges their effects, so it may rationalize its
own earlier decision. Measure this directly with: a successful tap followed by
failed save; an intermediate success message followed by reverted data; a screen
with similar visual structure but wrong target; and an uncertain mutation result.

Keep human-withheld labels as the evaluation authority. A separate AI reviewer
may assist triage on blinded trajectories but its agreement is not independent
ground truth. Record its model/prompt and disagreements; common model families,
training or the actor's explanation can correlate mistakes. Do not introduce a
runtime multi-agent judge as an unmeasured architectural requirement.

## Promotion and regression

Owner: QA proposes the suite and evidence; coordinator and product owner agree
promotion criteria before the benchmark. Provider/model choice, first real app,
device and numeric criteria remain open. A change to model, prompt, tools,
context compression, observation timing or image handling requires relevant
regression evaluation. Preserve a development set and a held-out set; freeze the
held-out set before measurement and do not tune on its individual answers.

Evaluate screenshot freshness, animation/loading and bounded observation waits.
Repeated wait is a model decision within technical budgets; neither a timer nor
the absence of pixel change constitutes an application pass. Preserve reports
when limits are reached instead of fabricating a semantic conclusion.
