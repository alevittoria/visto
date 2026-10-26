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
  device leases in the Visto home. Device inventory via a fixed, bounded
  `adb devices -l`; the backend starts the adb server at startup.
- **iOS tunnel**: on macOS `visto start` runs the XCUITest driver's tunnel script as
  root through sudo (one password prompt, credential refreshed while running,
  ownership and permission checks before escalating, `--no-ios-tunnel` to opt out),
  prints a notice when the script ends on its own, starts it again before a run on a
  physical iPhone when it has ended, and stops it after Appium. The tunnel only covers
  phones connected by USB cable. Refreshing the device list also
  tries to reconnect paired phones that CoreDevice reports as not connected.
- **iOS adapter**: Appium/XCUITest sessions bound to a simulator or an attached
  device, the same seven typed commands, and `back` as a dispatch-only swipe from
  the left screen edge that may not navigate — the AI judges the effect from the
  next observation and adapts. Screenshot pixels are converted to display points
  through one authority, with the ratio derived and validated per session and an
  inconsistent or non-uniform ratio refusing the device rather than guessing.
  WebDriverAgent signing values come from the settings store and are never
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
- **Interfaces**: `visto` CLI (`setup`, `start`, `doctor`, `settings`, `run`,
  `inspect`, observe-only mode, `--platform` with `ios` offered only on macOS);
  local FastAPI execution and settings API; React console (settings page with a
  write-only provider key, device picker, model choice, run
  view with action overlay, controls, questions, run history and deletion, "run
  again", statistics with daily-priced cost estimates, dictation); JSON/HTML
  report export. One device picker lists both platforms with the platform
  visible, selectability follows each platform's own state vocabulary, and a run
  cannot be submitted until a device list has confirmed the device's platform.
- **Installation**: a wheel attached to GitHub Releases (built by a tag-triggered
  workflow, with the compiled console and the Appium lockfiles inside) is
  installed with `uv tool install`. `visto setup` downloads pinned,
  checksum-verified portable Node, JDK and Android platform-tools/build-tools
  into the Visto home (`~/.visto`) after the Android SDK license is accepted,
  then installs Appium from the shipped lockfile (UiAutomator2 everywhere, plus
  XCUITest on macOS). No system environment variable or `PATH` is changed.
  `visto start` runs Appium as a child process and the backend, which also
  serves the console, from one terminal. Settings (provider key in an
  owner-only secrets file, iOS signing values, price refresh) are read at use;
  no environment variable or `.env` file configures them. The run
  database has numbered migrations with a backup before each, and a process
  registry keeps setup and migrations away from running Visto processes. See
  [installation](../local-development.md) and [iOS setup](../ios-setup.md).

## Verification state

- Local checks (`python scripts/verify.py`) cover backend tests, Ruff, build,
  frontend type-check/tests/build and companion integrity. They exercise
  software boundaries, not model judgement quality.
- The installation path (toolchain download and extraction, Appium install,
  `visto start` supervision, settings store and API, migrations, release
  workflow) has local checks, with fake downloads, processes and servers. The
  release workflow has run on GitHub for a version tag and attached a wheel that
  passes the wheel check; no clean host has been installed from a released wheel.
  The case-insensitive-filesystem archive guard is simulated, not observed on
  macOS.
- iOS has local checks against a fake HTTP wire for every adapter behaviour, and
  works on a physical iPhone once the setup is complete (WebDriverAgent built,
  signed and trusted, signing values saved, phone connected by USB cable): runs
  have been carried out end to end there. The XCUITest routes and the Xcode
  inventory commands were checked against driver documentation, driver sources
  and the installed toolchain's own output; `docs/references.md` records which
  claims rest on which evidence.
- Live smoke runs on a real phone have passed for positive and negative cases,
  pause/resume/cancel through the API, and the `long_press`/`enter` commands.
  This is preliminary smoke, not a labelled evaluation: the product is
  **unevaluated** for judgement quality.
- Not yet exercised live: console Cancel button, pending question/answer from the
  console, delayed UI, observe-only mode, CLI path, Appium/provider failure
  handling (expected: infrastructure failure, not a verdict).
- iOS not yet exercised live: the simulator path, the `connected` device mapping,
  rotation on hardware and the labelled acceptance scenario.

## Known issues

- AI false pass on procedure-shaped goals whose final state is already visible:
  the requested procedure is skipped and the run passes.
- Storage errors are logged without their original cause.
- An answer racing the run deadline returns 503.
- `cleanup_failed` is not durable.
- A failed session start whose outcome is uncertain leaves a device lease that needs
  manual cleanup. An explicit Appium refusal of the session request releases it, and
  on iOS a session created but found unusable is deleted once and the lease released
  when that delete succeeds.
- A failed session start is stored with a generic detail unless the adapter
  recognises the cause (iOS: phone not visible to Appium, WebDriverAgent launch
  failure); other causes, such as the exact `xcodebuild` error, are only in the
  Appium server log or the build result.
- The iOS tunnel, its sudo handling and the refresh reconnect have local checks
  only. Stopping the tunnel signals the sudo process Visto started and relies on sudo
  relaying the signal to the script (sudo was seen running a second sudo before node);
  that relay and `devicectl device info details` on a disconnected phone are
  unverified. The ownership checks cannot stop another process of the same user
  from replacing the files root runs.
- The tunnel script exits when no phone is on USB at start; Visto starts it again
  before the next run on a physical iPhone and waits for that phone's tunnel through
  the driver's registry. This relaunch has local checks only, and depends on the sudo
  credential cached at `visto start` still being valid. Simulators are told apart by
  their UUID-shaped device ID. `visto run` does not start the tunnel.
- After `visto start` restarts, the WebDriverAgent left on the phone is reused and
  refuses UI testing; the adapter deletes that session and retries once with
  `appium:useNewWDA`. The retry has local checks only; the stale-runner answers it
  recognises come from a real session.
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
5. Run the remaining iOS live checks: the simulator path, then the acceptance
   scenario on the simulator and the attached phone, following
   [iOS setup](../ios-setup.md) and [first device test](../first-device-test.md).
6. Live installation checks from a released wheel on a clean Windows host and a
   clean Mac (`visto setup`, `visto start`, Settings page, `visto doctor`, a run),
   then an upgrade from one release to the next with data and settings kept.
