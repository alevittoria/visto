# Testing and evaluation

See the [evaluation protocol](../evaluation/protocol.md) and the
[scenario matrix](../evaluation/scenarios.json).

## Local checks

After the [locked setup](../local-development.md):

```bash
python scripts/verify.py
```

The verifier invokes installed executables directly and derives project paths
from its location; use `--node <absolute-node-path>` if Node is not on PATH. It
checks the uv lock offline, pytest, Ruff lint/format, sdist/wheel build, strict
TypeScript compiler lint, native Node tests, the Vite production build and
companion integrity. No provider or Android calls are made.

Companion integrity alone, with Python 3.12+ and no packages installed:

```bash
python -m unittest discover -s scripts/tests -v
python scripts/check_project.py
```

The checker verifies that the context pack, key docs and role files exist; that
local Markdown links (inline, image, reference definitions) resolve inside the
repository, ignoring external URLs, anchors, inline code and fenced code; and
that role TOML parses with only `name`, `description` and
`developer_instructions`, names matching filenames. It is not a full Markdown
parser and does not prove document accuracy.

## What the tests cover

Backend tests cover frozen original request/expected result, strict command
types and JSON round trips, frame/scope/evidence identity, receipt timing,
question/answer lifecycle, first-terminal-wins, fake loop/Android/provider
contracts, local SQLite/artifact races, the killable provider child, the API and
composed fake-wire CLI. An AST guard checks domain/application imports (a
practical architecture check, not a sandbox). Frontend tests exercise response
validation, network/deadline failures, stale refresh, form, history, statistics
and speech logic; there are no DOM rendering tests.

## Evidence classes

| Layer | Checks | External resources |
|---|---|---|
| Domain/application | Typed action validity; goal preservation; state transitions; cancellation; budgets; evidence references; one device owner; uncertain command handling | None; fake clock/device/provider |
| Adapter contracts | Provider response parsing; malformed/partial responses; screenshot geometry; timeouts; SQLite/artifact consistency; redaction | Local fixtures and temporary storage |
| API/console | Request validation; run lifecycle; rendering; cancellation and error states | Local app and fake adapters |
| Live provider smoke | Image input, typed response conversion, usage reporting and bounded failure | Credentials and budget |
| Real device smoke | Screenshot, typed action and post-action observation; lock/release; session recovery | A selected Android device |
| Labelled evaluation | Quality of AI navigation and conclusions against withheld labels, including negative controls | Versioned scenarios, provider and device |

Tests of the runner's technical behavior must never evolve into static rules
that decide whether an application screen satisfies the user's goal. Fake
provider responses exercise orchestration, not model intelligence. Unit test
success is not semantic evaluation success; a live smoke is not an acceptance
benchmark. Keep each claim attached to its evidence class.

For behavioral changes, first reproduce the desired behavior with a failing
test, implement the smallest passing change and run the relevant tests.

## Live boundaries

Live checks name prerequisites, device ownership, test accounts, artifacts,
spend/time limits and the exact command before execution. Credentials stay out
of source and reports. Screenshots may contain private information and are sent
to the selected provider during live operation.

No numerical model-quality threshold is agreed yet. Establish it before a
promotion evaluation; never choose it after seeing that evaluation's results.
Until labelled evaluation exists, describe the product as unevaluated.
