# First device tests

The headless CLI drives the same single-conversation runner as the web console.
It runs inside the Docker stack or the dev container, against the containerized
Appium. See [Docker and dev container](docker.md) to start either one and to
connect a phone.

## Prepare device and provider

Use an authorized Android 8/API26 or newer device with USB debugging enabled and
visible to the `appium` container (`docker compose exec appium adb devices`).
Unlock it and manually open the target application in its starting state. Use
test accounts/data. Appium may install automation helper APKs on first
connection; it does not install/reset the target app. Keep other automation
clients away from this device during the run. No device is silently selected.

An OpenAI API key with billing/model access is required. Set `OPENAI_API_KEY` in
the repository-root `.env` (ignored) using `.env.example` as a safe template.
The file is read on every invocation; existing process environment wins. The key
is not copied into arguments, reports or request artifacts. Screenshots, goal,
action details and clarifications leave this computer for inference. See
[provider setup](provider-setup.md) for transmission/retention and
[artifact storage](artifact-storage.md) for private local evidence.

## First run on iOS

iOS needs the backend or CLI started natively on macOS, not in the containers.
Complete [iOS setup](ios-setup.md) first: install the pinned Appium stack, boot
the simulator or prepare the phone, and install WebDriverAgent. Check the
toolchain with `python -m visto.cli doctor --platform ios --device <udid>`, then
run an observation test as below with `--platform ios`:

```sh
python -m visto.cli run --platform ios --device <udid> --observe-only \
  --goal "Observe the current screen and check whether it shows the home screen. Conclude from visible evidence."
```

Run these commands from the repository root so the lease directory is shared
with the console. The iOS path has local checks only; no simulator or phone run
has been recorded, so treat a first iOS run as the first live evidence rather
than a confirmation.

## Run a first observation test

In the full stack the CLI runs in the backend container (`-it` keeps the terminal
interactive for questions):

```sh
docker compose exec -it backend python -m visto.cli run --device <serial> --observe-only \
  --goal "Observe the current screen and check whether it shows the home screen of the app under test. Conclude from visible evidence."
```

In the dev container terminal, from the repository root, use
`uv run --project backend --locked --no-sync python -m visto.cli` instead of
`python -m visto.cli`.

`--observe-only` supplies an empty mutation capability list. The AI can observe,
wait, ask and conclude; tap/swipe/text/key requests are rejected technically before
dispatch. This checks the screenshot/provider/result path. Inspect the AI judgement.

For a navigation test, manually return to a known starting screen and omit
`--observe-only`. For example (`Sample Notes` is a placeholder):

```sh
docker compose exec -it backend python -m visto.cli run --device <serial> \
  --goal "In Sample Notes, open the About page and verify that the app version is visibly listed." \
  --constraint "Do not modify data or install applications."
```

One AI judges navigation and meaning from screenshots. No page labels or success
predicates are coded into the runner. Default model is `gpt-6-luna`; `--model`
changes it explicitly. Account access is required; no fallback exists.
`--goal-file` or `--request-file` (UTF-8 JSON with `goal`, `constraints`,
`expected_result`) avoid shell quoting issues for long goals.

## Read the result and evidence

Output is newline-delimited JSON: starting run ID/configuration, essential
questions, then terminal result. Answer in the terminal; `/cancel`, EOF or Ctrl+C
cancels. Questions release device ownership; resumption captures a fresh image.
Wall time continues during input and is checked before reacquisition. Ctrl+C
during a command waits for its finite boundary; it cannot undo dispatched work.

| Exit code | Meaning |
|---|---|
| 0 | AI concluded passed |
| 1 | AI concluded failed |
| 2 | AI concluded inconclusive (doctor uses 2 for missing configuration) |
| 3 | Infrastructure/configuration failure, or cleanup failure requiring inspection |
| 4 | Technical budget exhausted |
| 130 | Cancelled |

After cleanup failure, output preserves any durable conclusion, adds
`cleanup_failed: true`, and exits 3. Inspect both fields. A successful tap never
means a passed test. `reported_usage` covers persisted decisions only; failed or
unrecorded requests may incur additional unknown usage.

History lives in `.work/runs/runs.sqlite3`, screenshots in `.work/runs/artifacts/`
(inside the stack's or dev container's volume). Inspect without key/device access:

```sh
docker compose exec backend python -m visto.cli inspect --run-id <run-id>
```

This prints original request, decisions, evidence references, receipts and terminal.
Never modify stored evidence.

## Limits and recovery

Defaults: 1200000ms wall time, 60 actions, 90 inferences, 60000ms per command/startup/
capture, 10000ms maximum requested wait. These technical budgets do not determine
semantic verdicts. Overrides and the configuration-only doctor:

```sh
docker compose exec backend python -m visto.cli run --help
docker compose exec backend python -m visto.cli doctor --device <serial>
```

Doctor contacts neither provider nor device. CLI and console share
`.work/device-leases`; do not start a CLI run on a device while the console has an
active run on it.

Uncertain mutation or unknown startup/cleanup retains the lease and never retries
the command automatically. Follow [Android recovery](android-setup.md) (or
[iOS recovery](ios-setup.md#recovery-of-a-retained-lease)) before a
new run. Process-crash auto-resume is unsupported; same-process question/answer
resume works.
