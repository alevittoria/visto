# Current status

Current state of the project only. Git history is the changelog; do not append
dated progress notes here.

## Implemented

- **Domain and application**: immutable typed contracts and a single-conversation
  run loop with fresh pre/post observations, bounded context, ask/answer,
  pause/resume, distinct semantic and technical terminal records, no blind
  retries of uncertain mutations, and a cancellable post-action settle delay
  (default 1500 ms, skipped for rejected commands).
- **Shared Appium core**: the platform-neutral half of a device adapter — HTTP
  wire, PNG framing checks, fail-closed lease marker, single-operation guard,
  source-frame validation, focused-element lookup and receipt/uncertainty
  semantics. Each platform supplies only its capabilities, its frame capture and
  its command translation.
- **Android adapter**: serial-bound Appium/UiAutomator2 sessions, native PNG and
  rotation validation, typed commands (`tap`, `long_press`, `swipe`, `type_text`
  as one whole-value set, `back`, `home`, `enter`) and fail-closed
  repository-scoped device leases. Device inventory via a fixed, bounded
  `adb devices -l`; the backend starts the adb server at startup.
- **iOS adapter**: Appium/XCUITest sessions bound to a simulator or an attached
  device, the same seven typed commands, and `back` as a dispatch-only swipe from
  the left screen edge that may not navigate — the AI judges the effect from the
  next observation and adapts. Screenshot pixels are converted to display points
  through one authority, with the ratio derived and validated per session and an
  inconsistent or non-uniform ratio refusing the device rather than guessing.
  WebDriverAgent signing values come from the process environment and are never
  committed. Device inventory from two independent fixed, bounded, read-only
  Xcode commands, one for simulators and one for attached devices, so a failure
  of either still lists the other.
- **AI adapter**: OpenAI Responses with structured decisions through a fixed
  HTTPS child process (secret via stdin, bounded lifecycle, sanitized error
  categories, redirects rejected). Instructions render from a shared core plus
  one versioned notes file per platform, `android-agent-v3` and `ios-agent-v1`;
  the rendered Android text is unchanged and a test pins it by digest.
  Selectable models from an allowlist. Audio transcription for dictated goals.
- **Storage**: SQLite run history and owned immutable screenshot artifacts with
  scoped provenance and first-terminal-wins finalization.
- **Platform selection**: a run carries its platform from the console or the API
  to the composition root, which is the one place a platform picks its adapter;
  the stored run records the choice through its existing adapter and instruction
  version strings, and neither domain nor application knows about platforms.
- **Interfaces**: headless CLI (`run`, `doctor`, `inspect`, observe-only mode,
  `--platform`); local FastAPI execution API; React console (device picker,
  model choice, run
  view with action overlay, controls, questions, run history and deletion, "run
  again", statistics with daily-priced cost estimates, dictation); JSON/HTML
  report export. One device picker lists both platforms with the platform
  visible, selectability follows each platform's own state vocabulary, and a run
  cannot be submitted until a device list has confirmed the device's platform.
- **Environment**: Appium, the backend and the console run as local processes.
  Windows and Linux drive Android with the pinned `tools/appium` package; macOS
  drives both platforms in one picker with `tools/appium/macos`, which adds the
  XCUITest driver. Root `.env` for credentials (process environment takes
  precedence). See [installation](../local-development.md) and
  [iOS setup](../ios-setup.md).

## Verification state

- Local checks (`python scripts/verify.py`) cover backend tests, Ruff, build,
  frontend type-check/tests/build and companion integrity. They exercise
  software boundaries, not model judgement quality.
- The iOS work has local checks only. Every iOS behaviour is verified against a
  fake HTTP wire: no simulator, no device, no Appium server and no provider has
  been contacted. The XCUITest routes and the Xcode inventory commands were
  checked against driver documentation, driver sources and the installed
  toolchain's own output, never a live session; `docs/references.md` records which
  claims rest on which evidence.
- Live smoke runs on a real phone have passed for positive and negative cases,
  pause/resume/cancel through the API, and the `long_press`/`enter` commands.
  This is preliminary smoke, not a labelled evaluation: the product is
  **unevaluated** for judgement quality.
- Not yet exercised live: console Cancel button, pending question/answer from the
  console, delayed UI, observe-only mode, CLI path, Appium/provider failure
  handling (expected: infrastructure failure, not a verdict).
- iOS on a phone: with the prebuilt WebDriverAgent found through
  `VISTO_IOS_WDA_DERIVED_DATA` and the developer profile trusted, a session
  started and a run executed actions. Its taps landed short of their targets,
  because the provider downscaled the screenshot and the model answered in the
  downscaled image's pixels; the adapter now sends screenshots already within
  the provider's limits and maps coordinates back. That fix has local checks
  only and has not been re-run on a device; it also changes the image sent for
  Android. The simulator path, the `connected` device mapping, rotation on
  hardware and the acceptance scenario remain unexercised. Android on macOS has not
  been re-checked either, and that setup is what the single picker needs.

## Known issues

- AI false pass on procedure-shaped goals whose final state is already visible:
  the requested procedure is skipped and the run passes.
- Storage errors are logged without their original cause.
- An answer racing the run deadline returns 503.
- `cleanup_failed` is not durable.
- A failed session start leaves a device lease that needs manual cleanup. On iOS
  a session created but found unusable is deleted once and the lease released
  when that delete succeeds; otherwise the lease is retained for manual recovery.
- A failed session start is stored with a generic detail; the cause (for example
  an `xcodebuild` error) is only in the Appium server log.
- Nothing compares a requested platform with the attached device: a mismatch
  surfaces only as a session that Appium cannot start.
- No DOM tests for React components.
- Transcription minutes are not included in cost statistics.

## Next work

1. Independent QA review of the console features (device picker, model choice,
   deletion, statistics, dictation), installation guide and Android commands.
2. Live checks for the scenarios listed under "Not yet exercised live".
3. Fix the known issues above, starting with the false-pass pattern.
4. Repeated labelled evaluation following the
   [evaluation protocol](../evaluation/protocol.md); agree numeric thresholds
   before running it.
5. Install the pinned macOS Appium stack, then run the iOS live checks: the
   simulator path first, then the attached device, then the acceptance scenario on
   both, following [iOS setup](../ios-setup.md) and
   [first device test](../first-device-test.md).
6. Re-check Android live with the backend on macOS, since that setup serves
   both platforms from one picker.
7. Live check of the installation guide on a clean Windows or Linux host: Appium
   from `tools/appium` with a local Android SDK and JDK, followed step by step.
