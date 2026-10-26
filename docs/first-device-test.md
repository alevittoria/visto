# First device tests

The headless CLI, `visto run`, drives the same single-conversation runner as the
web console. Install Visto and run `visto setup` first (see
[installation](local-development.md)). `visto run` uses the Appium of a running
`visto start` when one answers on its `--appium-url` port (default
`http://127.0.0.1:4723`); otherwise it starts its own Appium for the duration of
the run. The console is not required. The CLI uses the same Visto home as the
console, so it shares run history, settings and device leases with it.

## Prepare device and provider

Use an authorized Android 8/API26 or newer device with USB debugging enabled and
listed as ready by `visto doctor` (see [Android setup](android-setup.md#connect-a-device)).
Unlock it and manually open the target application in its starting state. Use
test accounts/data. Appium may install automation helper APKs on first
connection; it does not install/reset the target app. Keep other automation
clients away from this device during the run. No device is silently selected.

An OpenAI API key with billing/model access is required. Store it once on the
console's Settings page or with `visto settings set-key`, and check it with
`visto settings verify-key` (see [provider setup](provider-setup.md)). Each run
reads it from the Visto home when it starts. The key is not copied into
arguments, reports or request artifacts. Screenshots, goal,
action details and clarifications leave this computer for inference. See
[provider setup](provider-setup.md) for transmission/retention and
[artifact storage](artifact-storage.md) for private local evidence.

## First run on iOS

iOS needs macOS. Complete [iOS setup](ios-setup.md) first: boot the simulator or
prepare the phone, install WebDriverAgent and enter the signing values in
Settings. Check the setup with `visto doctor`, then run an observation test as
below with `--platform ios`:

```sh
visto run --platform ios --device <udid> --observe-only \
  --goal "Observe the current screen and check whether it shows the home screen. Conclude from visible evidence."
```

The iOS path has local checks only; no simulator or phone run
has been recorded, so treat a first iOS run as the first live evidence rather
than a confirmation.

## Run a first observation test

```sh
visto run --device <serial> --observe-only \
  --goal "Observe the current screen and check whether it shows the home screen of the app under test. Conclude from visible evidence."
```

In a checkout, contributors prefix every command with `uv run --project backend`
and pass `--home .work/home` (see
[installation](local-development.md#contributing)).

`--observe-only` supplies an empty mutation capability list. The AI can observe,
wait, ask and conclude; tap/swipe/text/key requests are rejected technically before
dispatch. This checks the screenshot/provider/result path. Inspect the AI judgement.

For a navigation test, manually return to a known starting screen and omit
`--observe-only`. For example (`Sample Notes` is a placeholder):

```sh
visto run --device <serial> \
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
| 2 | AI concluded inconclusive (doctor uses 2 when a check failed) |
| 3 | Infrastructure/configuration failure, or cleanup failure requiring inspection |
| 4 | Technical budget exhausted |
| 130 | Cancelled |

After cleanup failure, output preserves any durable conclusion, adds
`cleanup_failed: true`, and exits 3. Inspect both fields. A successful tap never
means a passed test. `reported_usage` covers persisted decisions only; failed or
unrecorded requests may incur additional unknown usage.

History lives in `~/.visto/data/runs.sqlite3`, screenshots in
`~/.visto/data/artifacts/` (`--data-dir` selects another folder). Inspect without
key/device access:

```sh
visto inspect --run-id <run-id>
```

This prints original request, decisions, evidence references, receipts and terminal.
Never modify stored evidence.

## Limits and recovery

Defaults: 1200000ms wall time, 60 actions, 90 inferences, 60000ms per command/startup/
capture, 10000ms maximum requested wait. These technical budgets do not determine
semantic verdicts. Overrides and the setup checks:

```sh
visto run --help
visto doctor
```

Doctor contacts no provider and no device beyond listing them. CLI and console
share `~/.visto/data/device-leases`; do not start a CLI run on a device while the
console has an active run on it.

Uncertain mutation or unknown startup/cleanup retains the lease and never retries
the command automatically. Follow [Android recovery](android-setup.md) (or
[iOS recovery](ios-setup.md#recovery-of-a-retained-lease)) before a
new run. Process-crash auto-resume is unsupported; same-process question/answer
resume works.
