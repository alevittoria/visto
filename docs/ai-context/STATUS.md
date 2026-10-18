# Current status

Current state of the project only. Git history is the changelog; do not append
dated progress notes here.

## Implemented

- **Domain and application**: immutable typed contracts and a single-conversation
  run loop with fresh pre/post observations, bounded context, ask/answer,
  pause/resume, distinct semantic and technical terminal records, no blind
  retries of uncertain mutations, and a cancellable post-action settle delay
  (default 1500 ms, skipped for rejected commands).
- **Android adapter**: serial-bound Appium/UiAutomator2 sessions, native PNG and
  rotation validation, typed commands (`tap`, `long_press`, `swipe`, `type_text`
  as one whole-value set, `back`, `home`, `enter`) and fail-closed
  repository-scoped device leases. Device inventory via a fixed, bounded
  `adb devices -l`; optional bridge to a host adb server for USB phones.
- **AI adapter**: OpenAI Responses with structured decisions through a fixed
  HTTPS child process (secret via stdin, bounded lifecycle, sanitized error
  categories, redirects rejected). Versioned instructions `android-agent-v3`.
  Selectable models from an allowlist. Audio transcription for dictated goals.
- **Storage**: SQLite run history and owned immutable screenshot artifacts with
  scoped provenance and first-terminal-wins finalization.
- **Interfaces**: headless CLI (`run`, `doctor`, `inspect`, observe-only mode);
  local FastAPI execution API; React console (device picker, model choice, run
  view with action overlay, controls, questions, run history and deletion, "run
  again", statistics with daily-priced cost estimates, dictation); JSON/HTML
  report export.
- **Environment**: Docker Compose stack and VS Code dev container; root `.env`
  for credentials (process environment takes precedence).

## Verification state

- Local checks (`python scripts/verify.py`) cover backend tests, Ruff, build,
  frontend type-check/tests/build and companion integrity. They exercise
  software boundaries, not model judgement quality.
- Live smoke runs on a real phone have passed for positive and negative cases,
  pause/resume/cancel through the API, and the `long_press`/`enter` commands.
  This is preliminary smoke, not a labelled evaluation: the product is
  **unevaluated** for judgement quality.
- Not yet exercised live: console Cancel button, pending question/answer from the
  console, delayed UI, observe-only mode, CLI path, Appium/provider failure
  handling (expected: infrastructure failure, not a verdict).

## Known issues

- AI false pass on procedure-shaped goals whose final state is already visible:
  the requested procedure is skipped and the run passes.
- Storage errors are logged without their original cause.
- An answer racing the run deadline returns 503.
- `cleanup_failed` is not durable.
- A failed session start leaves a device lease that needs manual cleanup.
- No DOM tests for React components.
- Transcription minutes are not included in cost statistics.

## Next work

1. Independent QA review of the console features (device picker, model choice,
   deletion, statistics, dictation), Docker setup and Android commands.
2. Live checks for the scenarios listed under "Not yet exercised live".
3. Fix the known issues above, starting with the false-pass pattern.
4. Repeated labelled evaluation following the
   [evaluation protocol](../evaluation/protocol.md); agree numeric thresholds
   before running it.
5. iOS adapter design behind the existing Device port.
