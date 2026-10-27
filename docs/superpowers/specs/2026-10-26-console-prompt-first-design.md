# Console redesign: prompt-first start, live-progress run view

## Intent

The console should communicate in one glance that writing the goal is all it takes
to start a run. In real use the contributor writes the prompt and presses start;
model, expected result, constraints, observe-only and limits almost always keep their
defaults. The current "New test run" page presents all of them as equal fields, plus
a large readiness panel and a fixed run list, so the prompt is one field among many.

During a run the contributor wants, in this order: the AI's reasoning about the
current screen; a quick scan of earlier decisions; an unmistakable signal when the AI
needs an answer; an unmistakable outcome at the end. The large live screenshot is
rarely useful and mildly annoying because it always lags behind.

## Decisions

### Why not a chat

A chat thread was considered and rejected (contributor agreed). An always-present
composer implies the user can steer mid-run, but the goal is fixed for the whole run
and the AI only accepts answers to its own questions (product rule in `AGENTS.md`).
In a thread, questions and the verdict are just another message, and old steps push
the current one away. The start screen borrows the chat-like affordance (one big
input), the run view does not.

### Start screen

- Centered heading "What do you want to test?" and one large goal textarea, focused
  on load. Enter starts the run, Shift+Enter inserts a newline. Dictation button
  inside the input.
- Below the text, inside the input frame, two chips and the start button:
  - **Device chip**: shows the selected device with its platform. Opens a device menu
    (list, selectable/non-selectable state, status hint, manual refresh).
  - **Options chip**: opens a panel with AI model, expected result, constraints,
    observe-only and limits (same fields, validation and help as today). When any value
    differs from the defaults the chip shows it (e.g. "Options · 2 changed") so an
    active constraint or observe-only is never forgotten.
- Readiness panel is removed as a permanent block. When something prevents starting
  (service unreachable, setup needed / provider key missing, configuration error, no
  ready device, a run already open, device cleanup attention) a single notice line
  appears above the input with the relevant link (Open settings, View open run, View
  run). When everything is fine, nothing is shown. Service version and Appium URL move
  to the Settings page.
- Privacy notice becomes one short line under the input, with a "details" disclosure
  holding the current full text (provider receives screenshots and test text, AI may
  operate the device unless observe-only, dictation audio). It must stay visible
  without interaction; it changes wording with observe-only as today.
- Create-run error and "uncertain start" handling (no automatic resubmission,
  Refresh) keep their current behavior and appear near the start button.

### Device discovery (fixes iOS friction)

Today the device list loads once on mount and then only on manual Refresh, so a phone
that becomes ready seconds later is missed. New behavior:

- Re-list when the device menu opens and when the browser tab regains focus/visibility.
- While the start screen is visible and no device is selectable, re-list on a bounded
  interval (builder picks, ~5 s); stop as soon as a selectable device exists, when a run
  is open, or when the page is hidden. Never overlap requests (abort previous, as today).
- When a selectable device appears and the user has not chosen another one, select it
  automatically (current `reconcileDevice`/`pickDevice` rules).
- Manual refresh stays in the menu.
- Note: on macOS listing also tries to reconnect paired iPhones; that is why polling
  is limited to "no ready device" and never runs during an open run.

### Run view

Top to bottom:

1. **Header**: goal clamped to 1–2 lines with expand; state badge with step count
   ("Running · step 4", "Paused", "Pausing…"); Pause / Resume / Cancel controls (cancel
   keeps its confirmation). Connection line stays compact (only prominent when lost).
2. **Question block** (only while the AI is waiting for an answer): strong colored
   block above everything else in the body, question text, answer field, send button,
   the existing note that the answer clarifies but does not change the goal. Sending
   an answer also resumes the run: answer request first, resume only after the answer
   is confirmed; an uncertain response follows the existing no-retry/Reconnect path.
   The page title should also signal it (e.g. prefix "Input needed") so it is noticed
   from another tab.
3. **Now block** (while running): the latest AI decision — reasoning about the current
   screen, the next action it is taking, and its judgement of the previous effect
   (achieved / not achieved / unclear). This replaces the large current-screen image.
4. **Outcome block** (terminal): replaces the Now block at the top, large and colored
   by outcome (passed / failed / inconclusive / infrastructure failure / cancelled /
   budget exhausted), with the explanation and the referenced screenshot thumbnails.
   Actions: primary **Rerun** (see below), secondary **Edit and rerun**, then minor
   links: readable report, JSON report, delete.
5. **Previous steps**: compact list, newest first, one row per step: step number,
   thumbnail, action summary, effect icon (✔ / ✖ / ?). Expanding a row shows the full
   reasoning, pre/post screenshots with the existing action overlay, receipts, and any
   question/answer in that step. Uses the existing `buildHistory` data.
6. **Details** (collapsed): device, mode, model, start time, tokens, cost, limits,
   expected result and constraints, unknown-usage note.

### Rerun

- **Rerun** starts a new run immediately with the same goal, expected result,
  constraints, model, mode, limits and device (`formFromRun` + existing request
  builder). It is one explicit click on a clearly labelled button; no extra confirm.
- If the device is not currently selectable, or the run cannot be created for a
  readiness reason, the button says why and "Edit and rerun" is the path forward.
- **Edit and rerun** = today's "Run again with these settings": back to the start
  screen with everything prefilled.

### Run history

- Narrow left sidebar, collapsible (state remembered in localStorage), ChatGPT/Claude
  style. Contains "New run" at the top and the run list (goal, outcome badge, time,
  cleanup warning, delete per row, delete all). Token summary moves to Stats.
- Top bar keeps Stats and Settings.
- On narrow viewports the sidebar becomes an overlay drawer opened from the top bar.

### Clarifications (designer's calls after builder review)

- **Step definition**: a step is one AI decision. "step N" counts decisions. Each row
  shows the decision's action (or "wait / look again", "asked a question" when there
  is no device action) and the effect icon for *that row's action* as judged by the
  next decision's `previous_effect`; the newest row shows a pending marker until judged.
  Rejected/uncertain receipts show on the row instead of an effect icon. Observations,
  questions/answers and unknown records attach to the step they fall in (expanded
  view); records before the first decision attach to step 1. No recorded evidence is
  dropped. Grouping lives in a pure `.ts` module with tests.
- **Rerun device check**: the run view does not list devices on open. Clicking Rerun
  performs one device listing; if the device is selectable, the run is created with
  its platform; otherwise no run is created and the user sees why with "Edit and
  rerun". If the original model is no longer offered, Rerun is blocked the same way
  (never silently falls back to another model).
- **Device cleanup attention** stays a warning, not a blocker (no behavior change):
  it appears in the notice line with "View run" links, but starting is still allowed.
- **Interrupted / not-controlled runs**: header badge as today ("Not controlled
  here"); a neutral block in place of Now/Outcome explaining that the run is not
  controlled by this console and no verdict is available here; previous steps shown;
  only "Edit and rerun" offered (no one-click Rerun).
- **Answer saved, resume rejected**: the question block shows the recorded answer, the
  rejection message and a visible Resume button. An uncertain resume follows the
  existing no-retry/Reconnect path.

## Non-goals

- No change to backend APIs, run semantics, polling cadence of runs, or safety
  behaviors (no automatic retry of mutations, delete confirmations, cancel confirm).
- No chat thread, no free-text messages to the AI during a run.
- No new visual identity; reuse current tokens/colors in `style.css`.

## Anti-goals (failure even if it works)

- Hiding the privacy notice behind a click only.
- Hiding non-default options so a user starts a run unaware of a constraint/observe-only.
- A Rerun that silently runs on a different device or with different settings.
- Polling device listing continuously while a run is open.

## Constraints

- React/TypeScript frontend only (`frontend/src`); keep pure logic in `.ts` modules
  with tests in `frontend/tests` (node test runner) as today.
- Accessibility at least as good as now: labels, aria-live for status/questions,
  focus management (focus goal on start screen, focus answer field when a question
  appears), keyboard operable menus/disclosures.
- UI text in English as today.
- Device anonymity rules from `AGENTS.md` for any fixture/example.
- Run `python scripts/verify.py` (frontend checks) and update
  `docs/ai-context/STATUS.md` and any affected docs (README screenshots/description
  of the console if they describe the old layout); run `python scripts/check_project.py`.

## Left to the builder

Exact visuals, spacing, icons, polling interval value, how the device menu and options
panel are implemented (popover vs. inline expansion), component split, sidebar width.
