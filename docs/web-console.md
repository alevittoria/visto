# Try a run from the web console

The console controls the same single-conversation runner as the terminal CLI.
The AI observes screenshots, chooses actions and concludes passed, failed or
inconclusive. Device/provider/storage errors, cancellation and exhausted budgets
are separate outcomes. Local software checks do not establish model accuracy.

## Start

Run `visto start` as described in
[installation](local-development.md#3-start-visto-visto-start); it opens the console
at <http://127.0.0.1:8000/> (or the `--port` you chose). iOS simulators and iPhones
appear only when Visto runs on macOS; see [iOS setup](ios-setup.md).

## Settings

The **Settings** button in the top bar (or `#settings`) opens the Settings page.
While no provider key is configured, the console opens it on its own. Changes apply
to the next run without restarting Visto.

- **AI provider key**: shows whether a key is configured and its last four
  characters. Paste a key and press **Save key** to set or replace it, **Verify**
  to check it without a billable request, **Remove** to delete it. The key is never
  shown again after saving and never reaches the console. See
  [provider setup](provider-setup.md).
- **Refresh model prices daily**: on by default. Turned off, the backend stops
  contacting the price source and cost estimates use the price lists already
  stored (see below).
- **iOS signing** (macOS only): the WebDriverAgent signing values, the prebuilt
  WebDriverAgent switch, the derived data folder and the read-only
  WebDriverAgent project path, with a notice when WebDriverAgent must be rebuilt.
  See [iOS setup](ios-setup.md#signing-values-physical-phone).

Save writes `settings.json` (and the key `secrets.json`) in the Visto home; see
[artifact storage](artifact-storage.md#visto-home).

## Run a bounded test

The start screen asks "What do you want to test?" with one large goal field,
focused on load. Name the app and what to check, using synthetic test data; the goal
is preserved for the full run and a changed objective belongs in a new run. Avoid
destructive operations unless deliberately authorized. **Enter** starts the run,
**Shift+Enter** adds a line. **Dictate** in the input records from the microphone
(stop it, or it stops after two minutes) and appends the server transcript to the
goal; the Options panel has one for the expected result. Review the text before starting. It needs a configured provider key, a browser that
can record WebM or MP4 audio, and a secure origin (`localhost` qualifies). The
recording is sent to OpenAI for transcription and is not stored locally.

Two chips sit under the goal, next to **Start**:

- **Device** shows the selected device with its platform. Its menu lists Android and
  iOS entries together; unauthorized, offline or shut-down entries are listed with the
  reason but cannot be selected. Follow [Android setup](android-setup.md) to prepare a
  phone. The list refreshes by itself when the menu opens, when the browser tab
  regains focus, and every few seconds while no device is selectable (it stops as soon
  as one is, while the page is hidden and while a run is open, because listing on
  macOS may try to reconnect paired iPhones). A newly ready device is selected
  automatically unless you picked another one; **Refresh** in the menu lists
  on demand. A shut-down iOS simulator must be started from Xcode first. Visto never
  boots a simulator or builds WebDriverAgent, but the driver will if a session targets
  a target that is not ready, so prepare it first; see [iOS setup](ios-setup.md).
  Configuration readiness does not prove physical connectivity or provider account
  access.
- **Options** opens a panel with the AI model (`gpt-6-luna` default,
  `gpt-5.6-terra`, `gpt-6-sol`; fixed for the whole run and shown in the run view;
  your account must have access to it, which is only checked when the run starts),
  the expected result, constraints, **Observe only** (removes mutation capabilities)
  and finite limits. When any value differs from the defaults the chip says so
  ("Options · 2 changed"), so a constraint or observe-only is never forgotten. Escape
  closes the panel and returns focus to the chip.

There is no permanent readiness panel. When something prevents starting (service
unreachable, provider key missing or configuration error, no ready device, a run
already open) one notice line above the input says why, with a link such as Open
settings or View open run. A device that needs cleanup attention is a warning with
View run links; starting is still allowed. A short privacy line under the input
stays visible and a "Privacy details" disclosure holds the full text: starting sends
screenshots and test text to the AI provider and, unless observe-only is set, lets the
AI operate the device. The Settings page shows the service version and the device automation service URL.

Start once. A start request whose response is lost is uncertain: use **Refresh**,
then inspect the history before submitting again.

The run view, top to bottom:

1. **Header**: the goal (two lines, expandable), a state badge with the step count
   ("Running · step 4", "Paused", "Waiting for your answer"), and Pause / Resume /
   Cancel run (cancel asks for confirmation). A step is one AI decision. The
   connection line is compact and turns prominent, with **Reconnect**, when updates
   are lost.
2. **Question block**, only while the AI waits for an answer, above everything else.
   Sending an answer also resumes the run: the answer is recorded first and resume is
   requested only after it is confirmed. The answer clarifies the AI's question but
   does not change the goal. If the answer is saved and resume is rejected, the
   block shows the answer, the reason and a **Resume** button. The browser tab title
   is prefixed "Input needed" while a question is open.
3. **Latest AI reasoning** while the run is going: the reasoning about the screen it
   last saw with that screenshot as a thumbnail, its next action, and its judgement of
   the previous action (achieved, not achieved or unclear). There is no large live
   screenshot.
4. **Outcome block** once the run ended, in place of the reasoning block, colored by
   outcome: "AI verdict" passed, failed or inconclusive with the AI's explanation and
   the screenshots it referenced; or "No verdict" for technical failure, cancelled
   or limit reached, with the technical detail. A completed tap is only a
   technical result; the terminal AI assessment owns the verdict. A run this console
   does not control (for example from a previous process) shows "Not controlled by
   this console" and no verdict.
5. **Steps**, newest first: one row per AI decision with its thumbnail, action and
   a check / cross / question mark for the AI's later judgement of that action. A
   rejected or uncertain technical receipt is shown instead of a mark. Expanding a row
   shows the full reasoning and plan, the screenshots before and after, receipts, and
   any question and answer in that step. Each tap, long press or swipe shows its source
   screenshot with the touched point (dashed ring for a long press) or swipe path
   marked.
6. **Details** (collapsed): device, mode, model, start time, tokens, estimated cost,
   limits, expected result and constraints.

Pause, answer and resume, and cancel are cooperative: in-flight operations settle
within their deadlines. Wait for the recorded lifecycle transition. Resume acquires
ownership and captures again.

**Rerun** in the outcome block starts a new run at once with the same goal, expected
result, constraints, model, mode, limits and device. It lists devices once when
clicked; if the device is not ready, or the original model is no longer offered, no
run is created, a notice next to the button says why and nothing falls back to another
device or model. **Edit and rerun** (the only option for a run not controlled here)
opens the start screen prefilled with those values; review it and start it as a new
run. The device stays selected only if it is still listed.

After inspecting a run, use **Open readable report** or **Download report data (JSON)** in the outcome block (while a run is going they are under Details). The readable
report contains links to this backend's screenshots; keep the service and local
artifacts available when viewing those links. See [reports](report-export.md).

## Run history

The left sidebar lists stored runs, newest first, with the goal, outcome badge, time
and a "Check device" warning when cleanup needs attention. **New run** at the top
returns to the start screen. The toggle at the left of the top bar hides or shows the
sidebar and remembers the choice in the browser; below 960 px wide the history is a
drawer opened from the same button (Escape closes it). Delete removes a finished
(or interrupted) run with its screenshots and history after confirmation;
"Delete all runs" keeps the run that is still open. Deletion is permanent and also
removes runs created by the CLI. Export reports first if you need to keep them.

Token usage: each run view shows input and output tokens under Details, and Stats
shows totals across all stored runs. Only persisted AI decisions are counted; failed
or unrecorded provider requests may have used tokens that are not shown.

Each run's Details show the estimated cost next to the tokens
(hover for the price list day and rates). Statistics (Stats button in the top
bar, or `#stats`) show outcome counts, "AI passed / AI conclusions", median and
range of duration and actions, and tokens across all stored runs, compared by model or by scenario (the exact same goal, expected
result and constraints; a rerun adds to it). Each scenario lists its newest
runs as outcome badges that open the run. These counts repeat each run's stored
result; they are not a labelled evaluation. The estimated cost uses the public
[AI Pricing Guru](https://www.aipricing.guru/) price list, which the backend
fetches once per UTC day (at start, then checked hourly) and keeps per day, so
each run is priced with the list of the day it was created. Runs older than the
first stored list are priced with it and marked "≈"; models without a price are
named, never guessed. Rates are base input/output prices; verify with the
provider before budgeting. Turn off "Refresh model prices daily" in Settings to
keep the backend from contacting the price source; costs then use the lists already
stored, and stay unpriced if none was ever fetched.

Only one web execution session is retained at a time, including paused and
waiting-for-answer runs. Finish or cancel it before creating another. Device
leases in the Visto home also coordinate with the CLI; unrelated Appium clients are
outside that cooperative lock.

## Disconnect, restart and privacy

If a start/control request loses its response, its acceptance is uncertain.
Reconnect and inspect history/current state before submitting another mutation.
A stale screenshot is retained evidence, not a live device view. No automatic
action replay is supported. A previous-process unfinished run stays inspectable
but cannot resume; reconcile surviving leases/Appium work before a fresh run.
See [artifact storage and recovery](artifact-storage.md).

Metadata and screenshots live in `~/.visto/data`; device ownership uses the
shared `~/.visto/data/device-leases`. The local API exposes test content and screenshots
to local readers. Do not share or publish these services. Evidence has no automatic
retention expiry and exports may contain private test text. Provider transmission
is remote inference; local storage does not imply provider zero retention.

Repeated labelled evaluation has not been run yet; see
[current status](ai-context/STATUS.md).
