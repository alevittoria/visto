# Evidence report export

The report adapter is a pure projection of a `Run` snapshot and its ordered
stored history. It performs no I/O, provider inference, device action, state
transition or application verification. JSON and readable HTML contain the
same recorded evidence; AI assessments remain model judgements.

## Python interface

```python
from visto.adapters.reports import render_html, render_json, report_data

run = await store.get(run_id)
history = await store.history(run_id)
json_text = render_json(run, history)
html_text = render_html(run, history)
data = report_data(run, history)  # versioned JSON-compatible dict
```

Callers own coherent snapshot acquisition, access control, response headers and
UTF-8 encoding. Recommended download content types are
`application/json; charset=utf-8` and `text/html; charset=utf-8`, with a generated
safe filename. The adapter neither writes files nor reads artifact bytes.

`history` accepts an ordered sequence of the existing application `RunRecord`
variants. Unsupported values and wrong-run records, including nested
assessments/artifact references, raise `ValueError` with safe fixed text.
Run and observation route identifiers must match
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. Current generated IDs meet this restriction;
unsafe identifiers fail closed instead of becoming links.

## Schema version 1

- `schema_version`: integer `1`.
- `outcome`: exactly `passed`, `failed`, `inconclusive`,
  `infrastructure_failure`, `cancelled`, `budget_exhausted`, or the current
  nonterminal lifecycle state. A completed command receipt never selects an
  outcome. The original terminal record remains present under `run.terminal`.
- `run`: all recorded run fields, original goal text/expected result/constraints,
  technical limits, capabilities, model/instruction/device adapter versions,
  pending question and terminal record. Dataclasses have explicit `type` names;
  enums use their string values and timestamps use ISO 8601 with timezone.
- `history`: all supplied records in their original order, with actions and
  command kinds/arguments, technical receipt status/detail/times, observations,
  exact presented evidence IDs, AI rationale and working plan, previous-effect
  assessments, per-decision model identity/usage and question/attributed answers.
- `timing`: stored creation/update times and elapsed milliseconds between those
  timestamps. `terminal_elapsed_ms` is null until terminal. An active run's
  snapshot elapsed time is not a live clock. Inference latency is not recorded
  by the domain and is not estimated.
- `reported_usage`: persisted-decision scope, decision count, token totals and
  known subtotals, counts of decisions missing each token metric, and unknown
  cost. A total is null if no decisions exist or any contributing value is
  unknown. A known subtotal of zero does not make an unknown total zero.
  Failed/unrecorded requests may consume additional unknown usage; even a fully
  known persisted-decision subtotal is not a complete provider billing claim.
- `notice`: the interpretation/snapshot limitations in plain text.

## Screenshots and inert HTML

Screenshot metadata retains artifact/run IDs, media type, size and SHA256,
without the internal `storage_key`. Each observation adds a generated same-origin
URL of the form `/api/runs/{run_id}/artifacts/{observation_id}`. No link is derived
from a storage path or user/model text. This projection does not verify that an
artifact is still available; the artifact endpoint must verify scope/integrity.

HTML escapes all request, observation-related, model and technical text. It has
no scripts, external assets, automatic image loads, forms or event handlers.
A restrictive CSP permits only the fixed inline presentation stylesheet;
screenshots are explicit links. The full ordered history uses native expandable
sections. Missing fields display `unknown / not recorded` and no HTML verdict is
inferred beyond the stored outcome.

The downloaded HTML needs the local service origin to resolve its root-relative
screenshot links. It is a readable evidence index rather than a self-contained
screenshot archive. JSON is standalone data, with the same service-relative
links. Report generation does not contact that service.

The adapter does not export internal host paths from artifact storage metadata.
Original free text is preserved verbatim in JSON and escaped in HTML; deliberately
provided text may itself contain paths or other private information. Reports and
linked screenshots retain the privacy sensitivity of the original run and have
no automatic redaction, encryption or retention lifecycle of their own. See
[artifact storage](artifact-storage.md) for the actual storage/access boundaries.

## Verification

From `backend/`, using the locked environment:

```sh
uv run --locked --no-sync pytest -p no:cacheprovider tests/test_reports.py -q
uv run --locked --no-sync ruff check src/visto/adapters/reports tests/test_reports.py
uv run --locked --no-sync ruff format --check src/visto/adapters/reports tests/test_reports.py
```

Tests cover all six terminal outcomes, all nonterminal lifecycle states, request
and ordered evidence fidelity, questions/answers, unknown usage, safe scoped
links, wrong-run rejection and malicious HTML text. They are local software
checks and make no claim about AI judgement quality or genuine device execution.
