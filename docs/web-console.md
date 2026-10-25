# Try a run from the web console

The console controls the same single-conversation runner as the terminal CLI.
The AI observes screenshots, chooses actions and concludes passed, failed or
inconclusive. Device/provider/storage errors, cancellation and exhausted budgets
are separate outcomes. Local software checks do not establish model accuracy.

## Start

Keep the configured API key in the ignored repository-root `.env`; the backend
loads it server-side and a nonblank process key takes precedence. Never put the
key in the frontend or a goal. See [provider setup](provider-setup.md).

Start Appium, the backend and the console as described in
[installation](local-development.md#4-start), then open
<http://127.0.0.1:5173>. iOS simulators and iPhones appear only when the backend
runs on macOS; see [iOS setup](ios-setup.md).

## Run a bounded test

1. Connect and unlock an Android device authorized for testing. Follow
   [Android setup](android-setup.md). Pick it from the Device dropdown (press
   Refresh after connecting or authorizing it); unauthorized/offline devices are
   listed with the reason but cannot be selected. The one list shows Android and
   iOS entries with the platform on each; the run uses the selected entry's
   platform. A shut-down iOS simulator is listed but not selectable: start it
   from Xcode, then Refresh. Visto never boots a simulator or builds
   WebDriverAgent, but the driver will if a session targets a target that is not
   ready, so prepare it first; see [iOS setup](ios-setup.md). Submission waits until the list
   confirms the platform. Configuration readiness does not
   prove physical connectivity or provider account access.
2. Pick the AI model (`gpt-6-luna` default, `gpt-5.6-terra`, `gpt-6-sol`); it is
   fixed for the whole run and shown in the run view. Your account must have
   access to the chosen model; that is only checked when the run starts.
3. Enter a goal, expected result and constraints. **Dictate** next to Goal and
   Expected result records from the microphone (stop it, or it stops after two
   minutes) and appends the server transcript to the field; review and correct
   it before starting. It needs a configured provider key, a browser that can
   record WebM or MP4 audio, and a secure origin (`localhost` qualifies). The
   recording is sent to OpenAI for transcription and is not stored locally. Name the intended app and use
   synthetic test data. The goal is preserved for the full run; a changed objective
   belongs in a new run. Avoid destructive operations unless deliberately authorized.
4. Set finite limits and optionally select observation-only mode, which removes
   mutation capabilities. Starting a run may send screenshots and goal/history
   text to the configured AI provider and, in normal mode, operate the device.
5. Start once. Inspect screenshot capture times, the AI's rationale and working
   plan, effect assessments and technical receipts in the history. A completed
   tap is only a technical result. The terminal AI assessment owns the verdict.
   Each tap, long press or swipe in the history shows its source screenshot
   with the touched point (dashed ring for a long press) or swipe path marked.
6. Pause, answer a pending question and resume, or cancel as needed. Controls are
   cooperative: in-flight operations settle within their deadlines. Wait for the
   recorded lifecycle transition. Resume acquires ownership and captures again.
7. Export JSON or HTML after inspecting a run. The readable report contains
   links to this backend's screenshots; keep the service and local artifacts
   available when viewing those links. See [reports](report-export.md).

Token usage: each run view shows input and output tokens, and the run list shows
totals across all stored runs. Only persisted AI decisions are counted; failed or
unrecorded provider requests may have used tokens that are not shown. No cost is
computed. Delete removes a finished (or interrupted) run with its screenshots and
history after confirmation; "Delete all runs" keeps the run that is still open.
Deletion is permanent and also removes runs created by the CLI. Export reports
first if you need to keep them. "Run again with these settings" in a run view
opens the new-run form prefilled with that run's goal, expected result,
constraints, model, mode and limits; review it and start it as a new run. The
device stays selected only if it is still listed.

Each run view shows its estimated cost next to the input and output tokens
(hover for the price list day and rates). Statistics (Stats button in the top
bar, or `#stats`): outcome counts, "AI passed /
AI conclusions", median and range of duration and actions, and tokens across all
stored runs, compared by model or by scenario (the exact same goal, expected
result and constraints; "Run again" adds to it). Each scenario lists its newest
runs as outcome badges that open the run. These counts repeat each run's stored
result; they are not a labelled evaluation. The estimated cost uses the public
[AI Pricing Guru](https://www.aipricing.guru/) price list, which the backend
fetches once per UTC day (at start, then checked hourly) and keeps per day, so
each run is priced with the list of the day it was created. Runs older than the
first stored list are priced with it and marked "≈"; models without a price are
named, never guessed. Rates are base input/output prices; verify with the
provider before budgeting. Set `VISTO_PRICE_REFRESH=off` to keep the backend
from contacting the price source (costs then stay unpriced).

Only one web execution session is retained at a time, including paused and
waiting-for-answer runs. Finish or cancel it before creating another. Repository
device leases also coordinate with the CLI; unrelated Appium clients are outside
that cooperative lock.

## Disconnect, restart and privacy

If a start/control request loses its response, its acceptance is uncertain.
Reconnect and inspect history/current state before submitting another mutation.
A stale screenshot is retained evidence, not a live device view. No automatic
action replay is supported. A previous-process unfinished run stays inspectable
but cannot resume; reconcile surviving leases/Appium work before a fresh run.
See [artifact storage and recovery](artifact-storage.md).

Metadata and screenshots use `.work/runs` by default; device ownership uses the
shared `.work/device-leases`. The local API exposes test content and screenshots
to local readers. Do not share or publish these services. Evidence has no automatic
retention expiry and exports may contain private test text. Provider transmission
is remote inference; local storage does not imply provider zero retention.

Repeated labelled evaluation has not been run yet; see
[current status](ai-context/STATUS.md).
